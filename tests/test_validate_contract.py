from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from smartstock_pipeline.validate_contract import (
    CONTRACTS,
    ContractValidationError,
    validate_csv,
    validate_database_contract,
    validate_outputs,
)


class ContractValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.paths = {
            table: Path(self.temp_dir.name) / f"{table}.csv" for table in CONTRACTS
        }

    def write_csv(self, table: str, header: tuple[str, ...], rows=()) -> None:
        with self.paths[table].open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)

    def write_valid_empty_outputs(self) -> None:
        for table, contract in CONTRACTS.items():
            self.write_csv(table, contract.headers)

    def test_all_five_header_only_outputs_validate(self) -> None:
        self.write_valid_empty_outputs()
        self.assertEqual(validate_outputs(self.paths), {table: 0 for table in CONTRACTS})

    def test_exact_headers_and_column_order_are_required(self) -> None:
        table = "products_materials"
        contract = CONTRACTS[table]
        wrong = list(contract.headers)
        wrong[0], wrong[1] = wrong[1], wrong[0]
        self.write_csv(table, tuple(wrong))

        count, errors = validate_csv(self.paths[table], table)

        self.assertEqual(count, 0)
        self.assertTrue(any("headers" in error for error in errors))

    def test_type_and_primary_key_errors_do_not_disclose_values(self) -> None:
        table = "orders"
        self.write_csv(
            table,
            CONTRACTS[table].headers,
            [("", "3", "not-an-id-secret", "open", "12.50")],
        )

        _, errors = validate_csv(self.paths[table], table)

        self.assertTrue(any("empty primary key" in error for error in errors))
        self.assertNotIn("not-an-id-secret", " ".join(errors))

    def test_invalid_decimal_and_csv_width_are_reported(self) -> None:
        table = "order_items"
        self.write_csv(
            table,
            CONTRACTS[table].headers,
            [("1", "2", "3", "not-numeric", "4.25", "unexpected")],
        )

        _, errors = validate_csv(self.paths[table], table)

        self.assertTrue(any("wrong number of fields" in error for error in errors))

    def test_all_five_schema_contracts_and_constraints_pass(self) -> None:
        def col_row(field, nullable):
            return (
                field.name,
                field.data_type,
                field.max_length,
                field.precision,
                field.scale,
                nullable,
            )

        def constraint_rows(table):
            contract = CONTRACTS[table]
            rows: list[tuple[str, str, str | None, str | None]] = [
                ("PRIMARY KEY", name, None, None) for name in contract.primary_key
            ]
            for foreign_key in contract.foreign_keys:
                rows.append(("FOREIGN KEY", *foreign_key))
            return rows

        class FakeConnection:
            def execute(self, query, params):
                table = params[0]
                if "information_schema.columns" in query:
                    contract = CONTRACTS[table]
                    return Mock(fetchall=lambda: [
                        col_row(field, "NO" if field.name in contract.primary_key else "YES")
                        for field in contract.fields
                    ])
                return Mock(fetchall=lambda: constraint_rows(table))

        self.assertEqual(validate_database_contract(FakeConnection()), [])

    def test_missing_schema_table_fails_critical_schema_validation(self) -> None:
        class MissingTableConnection:
            def execute(self, query, params):
                return Mock(fetchall=lambda: [])

        errors = validate_database_contract(MissingTableConnection())

        self.assertEqual(len(errors), len(CONTRACTS))
        self.assertTrue(all("required table is missing" in error for error in errors))

    def test_decimal_precision_timestamp_timezone_and_duplicate_keys_are_rejected(self) -> None:
        table = "products_materials"
        self.write_csv(
            table,
            CONTRACTS[table].headers,
            [
                ("1", "Glass", "Category", "0.001", "2", "active", "2026-11-18 12:00:00+00:00"),
                ("1", "Glass", "Category", "12345678901.00", "2", "active", "2026-11-18 12:00:00"),
            ],
        )

        _, errors = validate_csv(self.paths[table], table)

        self.assertTrue(any("duplicate primary key" in error for error in errors))
        self.assertEqual(sum("invalid" in error for error in errors), 3)

    def test_integer_values_must_fit_postgresql_integer_range(self) -> None:
        table = "inventory"
        self.write_csv(
            table,
            CONTRACTS[table].headers,
            [("2147483648", "7", "11", "3", "2026-11-18 12:30:00")],
        )

        _, errors = validate_csv(self.paths[table], table)

        self.assertTrue(any("invalid integer value in inventory_id" in error for error in errors))

    def test_missing_csv_path_is_rejected(self) -> None:
        self.write_valid_empty_outputs()
        paths = dict(self.paths)
        del paths["stock_movements"]

        with self.assertRaises(ContractValidationError) as raised:
            validate_outputs(paths)

        self.assertIn("stock_movements", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
