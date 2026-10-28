"""Validate PostgreSQL schemas and CSV files against the extraction contract."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

import psycopg

from smartstock_pipeline.db import (
    DatabaseConfigurationError,
    DatabaseConnectionError,
    connect,
)
from smartstock_pipeline.run_metadata import ExtractionRun, RunMetadataError, safe_error_summary


@dataclass(frozen=True)
class FieldContract:
    name: str
    data_type: str
    max_length: int | None = None
    precision: int | None = None
    scale: int | None = None


@dataclass(frozen=True)
class TableContract:
    fields: tuple[FieldContract, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[tuple[str, str, str], ...] = ()

    @property
    def headers(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)


CONTRACTS: dict[str, TableContract] = {
    "products_materials": TableContract(
        fields=(
            FieldContract("product_id", "integer"),
            FieldContract("product_name", "character varying", max_length=150),
            FieldContract("category", "character varying", max_length=100),
            FieldContract("unit_price", "numeric", precision=12, scale=2),
            FieldContract("reorder_level", "integer"),
            FieldContract("status", "character varying", max_length=30),
            FieldContract("updated_at", "timestamp without time zone"),
        ),
        primary_key=("product_id",),
    ),
    "inventory": TableContract(
        fields=(
            FieldContract("inventory_id", "integer"),
            FieldContract("product_id", "integer"),
            FieldContract("quantity_on_hand", "integer"),
            FieldContract("reorder_level", "integer"),
            FieldContract("last_updated", "timestamp without time zone"),
        ),
        primary_key=("inventory_id",),
        foreign_keys=(("product_id", "products_materials", "product_id"),),
    ),
    "orders": TableContract(
        fields=(
            FieldContract("order_id", "integer"),
            FieldContract("customer_id", "integer"),
            FieldContract("order_date", "date"),
            FieldContract("status", "character varying", max_length=30),
            FieldContract("total_amount", "numeric"),
        ),
        primary_key=("order_id",),
    ),
    "order_items": TableContract(
        fields=(
            FieldContract("order_item_id", "integer"),
            FieldContract("order_id", "integer"),
            FieldContract("product_id", "integer"),
            FieldContract("quantity", "numeric"),
            FieldContract("unit_price", "numeric", precision=12, scale=2),
        ),
        primary_key=("order_item_id",),
        foreign_keys=(
            ("order_id", "orders", "order_id"),
            ("product_id", "products_materials", "product_id"),
        ),
    ),
    "stock_movements": TableContract(
        fields=(
            FieldContract("movement_id", "integer"),
            FieldContract("product_id", "integer"),
            FieldContract("movement_type", "character varying", max_length=30),
            FieldContract("quantity", "integer"),
            FieldContract("movement_date", "timestamp without time zone"),
            FieldContract("reference_id", "integer"),
        ),
        primary_key=("movement_id",),
        foreign_keys=(("product_id", "products_materials", "product_id"),),
    ),
}

_TYPE_CHECKS = {
    "integer": lambda value: _is_integer(value),
    "numeric": lambda value: _is_decimal(value),
    "date": lambda value: _is_date(value),
    "timestamp without time zone": lambda value: _is_timestamp(value),
    "character varying": lambda value: True,
}


def _is_integer(value: str) -> bool:
    if not re.fullmatch(r"[+-]?\d+", value):
        return False
    digits = value.lstrip("+-")
    if len(digits) > 10:
        return False
    number = int(value)
    return -(2**31) <= number <= 2**31 - 1


def _is_decimal(value: str) -> bool:
    try:
        return Decimal(value).is_finite()
    except InvalidOperation:
        return False


def _is_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _is_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value)
        return len(value) > 10 and parsed.tzinfo is None
    except ValueError:
        return False


def _valid_field_value(field: FieldContract, value: str) -> bool:
    if not _TYPE_CHECKS[field.data_type](value):
        return False
    if field.max_length is not None and len(value) > field.max_length:
        return False
    if field.precision is not None and field.scale is not None:
        number = Decimal(value)
        digits = number.as_tuple().digits
        exponent = number.as_tuple().exponent
        if not isinstance(exponent, int):
            return False
        integer_digits = max(0, len(digits) + exponent)
        decimal_places = max(0, -exponent)
        if integer_digits > field.precision - field.scale or decimal_places > field.scale:
            return False
    return True


def _format_type(row: tuple) -> str:
    data_type, max_length, precision, scale = row
    if data_type == "character varying" and max_length is not None:
        return f"character varying({max_length})"
    if data_type == "numeric" and precision is not None:
        return f"numeric({precision},{scale})"
    return data_type


def validate_database_contract_report(connection) -> tuple[list[str], list[str]]:
    """Return critical schema errors and review warnings without reading business rows."""
    errors: list[str] = []
    warnings: list[str] = []
    for table_name, contract in CONTRACTS.items():
        rows = connection.execute(
            """SELECT column_name, data_type, character_maximum_length,
                      numeric_precision, numeric_scale, is_nullable
               FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = %s
               ORDER BY ordinal_position""",
            (table_name,),
        ).fetchall()
        if not rows:
            errors.append(f"{table_name}: required table is missing")
            continue

        actual = {row[0]: row[1:] for row in rows}
        expected_names = set(contract.headers)
        actual_names = set(actual)
        for name in contract.headers:
            if name not in actual:
                errors.append(f"{table_name}.{name}: required column is missing")
                continue
            data_type, max_length, precision, scale, is_nullable = actual[name]
            field = next(item for item in contract.fields if item.name == name)
            if data_type != field.data_type:
                errors.append(
                    f"{table_name}.{name}: expected {field.data_type}, got "
                    f"{_format_type((data_type, max_length, precision, scale))}"
                )
            elif field.max_length is not None and max_length != field.max_length:
                errors.append(
                    f"{table_name}.{name}: expected character limit "
                    f"{field.max_length}, got {max_length}"
                )
            elif field.precision is not None and (
                precision != field.precision or scale != field.scale
            ):
                errors.append(
                    f"{table_name}.{name}: expected numeric({field.precision},{field.scale}), "
                    f"got {_format_type((data_type, max_length, precision, scale))}"
                )
            if name in contract.primary_key and is_nullable != "NO":
                errors.append(f"{table_name}.{name}: primary key column must be NOT NULL")

        for name in sorted(actual_names - expected_names):
            warnings.append(f"{table_name}.{name}: unexpected source column; excluded from export")

        constraints = connection.execute(
            """SELECT tc.constraint_type, kcu.column_name,
                      ccu.table_name, ccu.column_name
               FROM information_schema.table_constraints AS tc
               JOIN information_schema.key_column_usage AS kcu
                 ON tc.constraint_catalog = kcu.constraint_catalog
                AND tc.constraint_schema = kcu.constraint_schema
                AND tc.constraint_name = kcu.constraint_name
               LEFT JOIN information_schema.constraint_column_usage AS ccu
                 ON tc.constraint_catalog = ccu.constraint_catalog
                AND tc.constraint_schema = ccu.constraint_schema
                AND tc.constraint_name = ccu.constraint_name
               WHERE tc.table_schema = current_schema() AND tc.table_name = %s
                 AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
               ORDER BY tc.constraint_type, kcu.ordinal_position""",
            (table_name,),
        ).fetchall()
        actual_primary = tuple(row[1] for row in constraints if row[0] == "PRIMARY KEY")
        if actual_primary != contract.primary_key:
            errors.append(
                f"{table_name}: expected primary key {contract.primary_key}, got {actual_primary}"
            )
        actual_foreign = {
            (row[1], row[2], row[3]) for row in constraints if row[0] == "FOREIGN KEY"
        }
        for foreign_key in contract.foreign_keys:
            if foreign_key not in actual_foreign:
                errors.append(f"{table_name}: required foreign key {foreign_key} is missing")
        for foreign_key in sorted(actual_foreign - set(contract.foreign_keys)):
            errors.append(f"{table_name}: unexpected foreign key {foreign_key}")
    return errors, warnings


def validate_database_contract(connection) -> list[str]:
    """Return critical schema errors; non-critical differences are separate warnings."""
    errors, _warnings = validate_database_contract_report(connection)
    return errors


def validate_csv(path: str | Path, table_name: str) -> tuple[int, list[str]]:
    """Validate exact headers and cell types; never include cell values in errors."""
    if table_name not in CONTRACTS:
        raise ValueError(f"Unknown extraction table: {table_name}")
    contract = CONTRACTS[table_name]
    errors: list[str] = []
    row_count = 0
    with Path(path).expanduser().open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source, strict=True)
        try:
            headers = next(reader)
        except StopIteration:
            return 0, [f"{table_name}: CSV is empty and has no header"]
        if tuple(headers) != contract.headers:
            return 0, [f"{table_name}: CSV headers do not match the documented contract"]

        primary_indexes = tuple(contract.headers.index(name) for name in contract.primary_key)
        seen_primary_keys: set[tuple[str, ...]] = set()
        for row_number, row in enumerate(reader, start=2):
            row_count += 1
            if len(row) != len(contract.fields):
                errors.append(f"{table_name}: row {row_number} has the wrong number of fields")
                continue
            primary_key = tuple(row[index] for index in primary_indexes)
            if any(value == "" for value in primary_key):
                errors.append(f"{table_name}: row {row_number} has an empty primary key")
            elif primary_key in seen_primary_keys:
                errors.append(f"{table_name}: row {row_number} has a duplicate primary key")
            else:
                seen_primary_keys.add(primary_key)
            for field, value in zip(contract.fields, row):
                if value == "":
                    continue
                if not _valid_field_value(field, value):
                    errors.append(
                        f"{table_name}: row {row_number} has an invalid {field.data_type} "
                        f"value in {field.name}"
                    )
    return row_count, errors


def validate_foreign_key_rows(paths: Mapping[str, str | Path]) -> list[str]:
    """Check CSV foreign-key references without exposing identifier values."""
    primary_values: dict[str, set[str]] = {}
    table_rows: dict[str, list[tuple[int, list[str]]]] = {}
    for table_name, contract in CONTRACTS.items():
        with Path(paths[table_name]).expanduser().open(encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source, strict=True)
            next(reader)
            rows = [(row_number, row) for row_number, row in enumerate(reader, start=2)]
        table_rows[table_name] = rows
        primary_indexes = tuple(contract.headers.index(field) for field in contract.primary_key)
        primary_values[table_name] = {
            row[index]
            for _, row in rows
            if len(row) == len(contract.fields)
            and all(row[index] != "" for index in primary_indexes)
            for index in primary_indexes
        }

    errors: list[str] = []
    for table_name, contract in CONTRACTS.items():
        for field_name, referenced_table, _referenced_field in contract.foreign_keys:
            field_index = contract.headers.index(field_name)
            for row_number, row in table_rows[table_name]:
                if len(row) != len(contract.fields):
                    continue
                value = row[field_index]
                if value and value not in primary_values[referenced_table]:
                    errors.append(
                        f"{table_name}: row {row_number} has an unresolved foreign key in {field_name}"
                    )
    return errors


def validate_source_counts(connection, csv_counts: Mapping[str, int]) -> list[str]:
    """Compare validated CSV row counts with one-snapshot source table counts."""
    count_queries = " UNION ALL ".join(
        f"SELECT '{table_name}'::text AS table_name, COUNT(*)::BIGINT AS row_count "
        f"FROM {table_name}"
        for table_name in CONTRACTS
    )
    source_counts = dict(connection.execute(count_queries).fetchall())
    return [
        f"{table_name}: CSV row count {csv_counts[table_name]} does not match "
        f"source row count {source_counts[table_name]}"
        for table_name in CONTRACTS
        if csv_counts[table_name] != source_counts[table_name]
    ]


def validate_outputs(
    paths: Mapping[str, str | Path],
    connection=None,
    *,
    warning_sink: list[str] | None = None,
) -> dict[str, int]:
    """Validate CSVs and schema; return non-critical source-schema warnings separately."""
    errors: list[str] = []
    if set(paths) != set(CONTRACTS):
        missing = sorted(set(CONTRACTS) - set(paths))
        extra = sorted(set(paths) - set(CONTRACTS))
        if missing:
            errors.append("Missing CSV path(s): " + ", ".join(missing))
        if extra:
            errors.append("Unknown CSV path(s): " + ", ".join(extra))
    if connection is not None:
        schema_errors, schema_warnings = validate_database_contract_report(connection)
        errors.extend(schema_errors)
        if warning_sink is None:
            errors.extend(schema_warnings)
        else:
            warning_sink.extend(schema_warnings)

    counts: dict[str, int] = {}
    for table_name in CONTRACTS:
        if table_name not in paths:
            continue
        try:
            counts[table_name], csv_errors = validate_csv(paths[table_name], table_name)
            errors.extend(csv_errors)
        except (OSError, csv.Error, UnicodeError) as exc:
            errors.append(f"{table_name}: could not read CSV ({type(exc).__name__})")
    if not errors:
        try:
            errors.extend(validate_foreign_key_rows(paths))
        except (OSError, csv.Error, UnicodeError) as exc:
            errors.append(f"Could not check CSV foreign keys ({type(exc).__name__})")
    if connection is not None and not errors:
        count_warnings = validate_source_counts(connection, counts)
        if warning_sink is None:
            errors.extend(count_warnings)
        else:
            warning_sink.extend(count_warnings)
    if errors:
        raise ContractValidationError(errors, counts)
    return counts


class ContractValidationError(ValueError):
    """Raised when a source schema or output CSV violates the data contract."""

    def __init__(self, errors: list[str], counts: Mapping[str, int] | None = None):
        self.errors = tuple(errors)
        self.counts = dict(counts or {})
        super().__init__("Extraction contract validation failed: " + "; ".join(errors))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the five extraction CSVs and PostgreSQL data contract."
    )
    for table_name in CONTRACTS:
        parser.add_argument(f"--{table_name.replace('_', '-')}", required=True)
    parser.add_argument(
        "--csv-only",
        action="store_true",
        help="Validate CSV contracts without connecting to PostgreSQL or comparing source row counts.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = {
        table_name: getattr(args, table_name)
        for table_name in CONTRACTS
    }
    run = ExtractionRun(tuple(CONTRACTS))
    counts: dict[str, int] = {}
    validation_warnings: list[str] = []
    try:
        with run:
            try:
                if args.csv_only:
                    counts = validate_outputs(paths)
                else:
                    with connect() as connection:
                        counts = validate_outputs(
                            paths,
                            connection,
                            warning_sink=validation_warnings,
                        )
            except ContractValidationError as exc:
                run.record_validation_errors(exc.errors)
                run.record_validation_warnings(validation_warnings)
                for table_name, count in exc.counts.items():
                    run.record_counts(
                        table_name,
                        records_read=count,
                        records_extracted=count,
                    )
                raise
            run.record_validation_warnings(validation_warnings)
            for table_name, count in counts.items():
                run.record_counts(
                    table_name,
                    records_read=count,
                    records_extracted=count,
                )
    except ContractValidationError as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 1
    except (
        DatabaseConfigurationError,
        DatabaseConnectionError,
        RunMetadataError,
        OSError,
        psycopg.Error,
    ) as exc:
        print(f"Validation failed: {safe_error_summary(exc)}", file=sys.stderr)
        return 1
    if validation_warnings:
        for warning in validation_warnings:
            print(f"Manual review required: {warning}", file=sys.stderr)
    print("Extraction contract validation passed: " + ", ".join(
        f"{name}={counts[name]} row(s)" for name in CONTRACTS
    ) + f" (run_id={run.run_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
