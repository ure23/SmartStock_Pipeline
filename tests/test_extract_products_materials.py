from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from smartstock_pipeline.extract_products_materials import (
    FIELDS,
    ExtractionError,
    extract_products_materials,
)


class ProductsMaterialsExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.output = Path(self.temp_dir.name) / "products_materials.csv"
        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection

    def set_source_results(self, columns: list[str], rows: list[tuple]) -> None:
        columns_result = MagicMock()
        columns_result.fetchall.return_value = [(column,) for column in columns]
        rows_result = MagicMock()
        rows_result.fetchall.return_value = rows
        self.connection.execute.side_effect = [columns_result, rows_result]

    @patch("smartstock_pipeline.extract_products_materials.connect")
    def test_exports_required_fields_and_source_rows(self, mock_connect: MagicMock) -> None:
        row = (
            7,
            "Clear Glass",
            "Glass",
            Decimal("12.50"),
            3,
            "active",
            datetime(2026, 11, 18, 12, 30, 0),
        )
        self.set_source_results(list(FIELDS), [row])
        mock_connect.return_value = self.connection

        count = extract_products_materials(self.output)

        self.assertEqual(count, 1)
        with self.output.open(encoding="utf-8", newline="") as csv_file:
            result = list(csv.reader(csv_file))
        self.assertEqual(result[0], list(FIELDS))
        self.assertEqual(
            result[1],
            ["7", "Clear Glass", "Glass", "12.50", "3", "active", "2026-11-18 12:30:00"],
        )
        self.connection.execute.assert_any_call(
            "SELECT " + ", ".join(FIELDS) + " FROM products_materials ORDER BY product_id"
        )

    @patch("smartstock_pipeline.extract_products_materials.connect")
    def test_empty_source_writes_header_only_csv(self, mock_connect: MagicMock) -> None:
        self.set_source_results(list(FIELDS), [])
        mock_connect.return_value = self.connection

        count = extract_products_materials(self.output)

        self.assertEqual(count, 0)
        with self.output.open(encoding="utf-8", newline="") as csv_file:
            self.assertEqual(list(csv.reader(csv_file)), [list(FIELDS)])

    @patch("smartstock_pipeline.extract_products_materials.connect")
    def test_missing_required_column_fails_without_creating_output(
        self, mock_connect: MagicMock
    ) -> None:
        self.set_source_results([field for field in FIELDS if field != "status"], [])
        mock_connect.return_value = self.connection

        with self.assertRaisesRegex(ExtractionError, "status"):
            extract_products_materials(self.output)

        self.assertFalse(self.output.exists())
        self.assertEqual(self.connection.execute.call_count, 1)

    @patch("smartstock_pipeline.extract_products_materials.connect")
    def test_duplicate_primary_keys_fail_without_creating_output(
        self, mock_connect: MagicMock
    ) -> None:
        row = (7, "Clear Glass", "Glass", Decimal("12.50"), 3, "active", None)
        self.set_source_results(list(FIELDS), [row, row])
        mock_connect.return_value = self.connection

        with self.assertRaisesRegex(ExtractionError, "duplicate product_id"):
            extract_products_materials(self.output)

        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
