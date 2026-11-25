"""Export orders and order items to separate related CSV files."""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

import psycopg

from smartstock_pipeline.db import (
    DatabaseConfig,
    DatabaseConfigurationError,
    DatabaseConnectionError,
    connect,
)
from smartstock_pipeline.run_metadata import (
    ExtractionRun,
    RunMetadataError,
    safe_error_summary,
)

ORDERS_FIELDS = ("order_id", "customer_id", "order_date", "status", "total_amount")
ORDER_ITEMS_FIELDS = ("order_item_id", "order_id", "product_id", "quantity", "unit_price")


class ExtractionError(RuntimeError):
    """Raised when a source table does not satisfy its extraction contract."""


def _fetch_table(connection, table_name: str, fields: tuple[str, ...], primary_key: str):
    column_rows = connection.execute(
        """SELECT column_name
           FROM information_schema.columns
           WHERE table_schema = current_schema() AND table_name = %s""",
        (table_name,),
    ).fetchall()
    source_columns = {row[0] for row in column_rows}
    missing = [field for field in fields if field not in source_columns]
    if missing:
        raise ExtractionError(
            f"Source table {table_name} is missing required column(s): "
            + ", ".join(missing)
        )

    query = f"SELECT {', '.join(fields)} FROM {table_name} ORDER BY {primary_key}"
    rows = connection.execute(query).fetchall()
    primary_key_index = fields.index(primary_key)
    identifiers = [row[primary_key_index] for row in rows]
    if len(identifiers) != len(set(identifiers)):
        raise ExtractionError(f"Source query returned duplicate {primary_key} values")
    return rows


def _write_csv(output_path: Path, fields: tuple[str, ...], rows: list[tuple]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
            writer = csv.writer(temporary_file, lineterminator="\n")
            writer.writerow(fields)
            writer.writerows(rows)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, output_path)
    except OSError:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
        raise


def extract_orders_and_items(
    orders_output_path: str | Path,
    order_items_output_path: str | Path,
    config: DatabaseConfig | None = None,
) -> tuple[int, int]:
    """Export the orders and order_items tables to separate CSV files.

    Both tables are read from one repeatable-read, read-only transaction so
    their shared order_id relationship represents the same database snapshot.
    Each output file is atomically replaced after its own successful write.
    """
    orders_output = Path(orders_output_path).expanduser()
    items_output = Path(order_items_output_path).expanduser()
    if orders_output.resolve() == items_output.resolve():
        raise ExtractionError("Orders and order_items outputs must be different files")

    with connect(config) as connection:
        connection.execute(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
        )
        orders_rows = _fetch_table(connection, "orders", ORDERS_FIELDS, "order_id")
        items_rows = _fetch_table(
            connection, "order_items", ORDER_ITEMS_FIELDS, "order_item_id"
        )

    _write_csv(orders_output, ORDERS_FIELDS, orders_rows)
    _write_csv(items_output, ORDER_ITEMS_FIELDS, items_rows)
    return len(orders_rows), len(items_rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export orders and order_items to separate UTF-8 CSV files."
    )
    parser.add_argument(
        "--orders-output",
        required=True,
        help="Destination path for orders.csv",
    )
    parser.add_argument(
        "--order-items-output",
        required=True,
        help="Destination path for order_items.csv",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    run = ExtractionRun(("orders", "order_items"))
    orders_count = 0
    items_count = 0
    try:
        with run:
            orders_count, items_count = extract_orders_and_items(
                args.orders_output, args.order_items_output
            )
            run.record_counts(
                "orders",
                records_read=orders_count,
                records_extracted=orders_count,
            )
            run.record_counts(
                "order_items",
                records_read=items_count,
                records_extracted=items_count,
            )
    except (
        DatabaseConfigurationError,
        DatabaseConnectionError,
        ExtractionError,
        RunMetadataError,
        OSError,
        psycopg.Error,
    ) as exc:
        print(f"Extraction failed: {safe_error_summary(exc)}", file=sys.stderr)
        return 1

    print(
        f"Exported {orders_count} order(s) to {Path(args.orders_output).expanduser()} "
        f"and {items_count} order item(s) to {Path(args.order_items_output).expanduser()} "
        f"(run_id={run.run_id})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
