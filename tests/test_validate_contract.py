from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from smartstock_pipeline.validate_contract import (
    CONTRACTS,
    ContractValidationError,
    validate_csv,
    validate_database_contract,
    validate_outputs,
    validate_source_counts,
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

    def test_foreign_key_rows_must_resolve_without_exposing_identifier_values(self) -> None:
        self.write_csv(
            "products_materials",
            CONTRACTS["products_materials"].headers,
            [("1", "Glass", "Category", "1.00", "2", "active", "2026-11-18 12:00:00")],
        )
        self.write_csv(
            "orders",
            CONTRACTS["orders"].headers,
            [("2", "4", "2026-11-18", "open", "4.00")],
        )
        self.write_csv(
            "order_items",
            CONTRACTS["order_items"].headers,
            [("5", "999", "1", "2", "2.00")],
        )
        for table in ("inventory", "stock_movements"):
            self.write_csv(table, CONTRACTS[table].headers)

        with self.assertRaises(ContractValidationError) as raised:
            validate_outputs(self.paths)

        self.assertTrue(
            any(
                error == "order_items: row 2 has an unresolved foreign key in order_id"
                for error in raised.exception.errors
            )
        )
        self.assertNotIn("999", str(raised.exception))

    def test_valid_csv_foreign_key_references_pass(self) -> None:
        self.write_csv(
            "products_materials",
            CONTRACTS["products_materials"].headers,
            [("1", "Glass", "Category", "1.00", "2", "active", "2026-11-18 12:00:00")],
        )
        self.write_csv(
            "orders",
            CONTRACTS["orders"].headers,
            [("2", "4", "2026-11-18", "open", "4.00")],
        )
        self.write_csv(
            "order_items",
            CONTRACTS["order_items"].headers,
            [("5", "2", "1", "2", "2.00")],
        )
        self.write_csv("inventory", CONTRACTS["inventory"].headers, [("1", "1", "3", "2", "")])
        self.write_csv("stock_movements", CONTRACTS["stock_movements"].headers)

        counts = validate_outputs(self.paths)

        self.assertEqual(counts["order_items"], 1)
        self.assertEqual(counts["inventory"], 1)

    @patch("smartstock_pipeline.validate_contract.validate_database_contract", return_value=[])
    def test_source_counts_match_validated_csv_row_counts(self, _schema_validation) -> None:
        self.write_valid_empty_outputs()
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = [
            (table, 0) for table in CONTRACTS
        ]

        counts = validate_outputs(self.paths, connection)

        self.assertEqual(counts, {table: 0 for table in CONTRACTS})
        query = connection.execute.call_args.args[0]
        for table in CONTRACTS:
            self.assertIn(f"FROM {table}", query)

    @patch("smartstock_pipeline.validate_contract.validate_database_contract", return_value=[])
    def test_source_count_mismatch_fails_with_aggregate_diagnostic(self, _schema_validation) -> None:
        self.write_valid_empty_outputs()
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = [
            (table, 7 if table == "orders" else 0) for table in CONTRACTS
        ]

        with self.assertRaises(ContractValidationError) as raised:
            validate_outputs(self.paths, connection)

        self.assertTrue(
            any(
                error == "orders: CSV row count 0 does not match source row count 7"
                for error in raised.exception.errors
            )
        )
        self.assertNotIn("secret", str(raised.exception))

    @patch("smartstock_pipeline.validate_contract.validate_database_contract", return_value=[])
    def test_cli_logs_validation_failure_and_value_free_errors(self, _schema_validation) -> None:
        from smartstock_pipeline.validate_contract import main

        self.write_valid_empty_outputs()
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.fetchall.return_value = [
            (table, 3 if table == "orders" else 0) for table in CONTRACTS
        ]
        arguments = [
            argument
            for table, path in self.paths.items()
            for argument in (f"--{table.replace('_', '-')}", str(path))
        ]
        stderr = io.StringIO()
        log_dir = Path(self.temp_dir.name) / "logs"

        with patch.dict(os.environ, {"SMARTSTOCK_LOG_DIR": str(log_dir)}):
            with patch("smartstock_pipeline.validate_contract.connect", return_value=connection):
                with redirect_stderr(stderr):
                    result = main(arguments)

        self.assertEqual(result, 1)
        self.assertIn("orders: CSV row count 0 does not match source row count 3", stderr.getvalue())
        self.assertNotIn("client-cell-secret", stderr.getvalue())
        logs = list(log_dir.glob("*.json"))
        self.assertEqual(len(logs), 1)
        metadata = json.loads(logs[0].read_text(encoding="utf-8"))
        self.assertEqual(metadata["validation_result"], "FAIL")
        self.assertEqual(
            metadata["validation_errors"],
            ["orders: CSV row count 0 does not match source row count 3"],
        )
        self.assertEqual(metadata["records"]["orders"]["records_read"], 0)

    def test_missing_csv_path_is_rejected(self) -> None:
        self.write_valid_empty_outputs()
        paths = dict(self.paths)
        del paths["stock_movements"]

        with self.assertRaises(ContractValidationError) as raised:
            validate_outputs(paths)

        self.assertIn("stock_movements", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
