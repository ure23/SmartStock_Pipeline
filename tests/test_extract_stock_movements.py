from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from smartstock_pipeline.extract_stock_movements import (
    FIELDS,
    ExtractionError,
    extract_stock_movements,
)


class StockMovementsExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.output = Path(self.temp_dir.name) / "stock_movements.csv"
        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection

    def set_source_results(self, columns: list[str], rows: list[tuple]) -> None:
        columns_result = MagicMock()
        columns_result.fetchall.return_value = [(column,) for column in columns]
        rows_result = MagicMock()
        rows_result.fetchall.return_value = rows
        self.connection.execute.side_effect = [columns_result, rows_result]

    @patch("smartstock_pipeline.extract_stock_movements.connect")
    def test_exports_required_fields_and_source_rows(self, mock_connect: MagicMock) -> None:
        row = (9, 4, "adjustment", 6, datetime(2026, 11, 18, 12, 30, 0), 75)
        self.set_source_results(list(FIELDS), [row])
        mock_connect.return_value = self.connection

        count = extract_stock_movements(self.output)

        self.assertEqual(count, 1)
        with self.output.open(encoding="utf-8", newline="") as csv_file:
            result = list(csv.reader(csv_file))
        self.assertEqual(result[0], list(FIELDS))
        self.assertEqual(
            result[1],
            ["9", "4", "adjustment", "6", "2026-11-18 12:30:00", "75"],
        )
        self.connection.execute.assert_any_call(
            "SELECT " + ", ".join(FIELDS) + " FROM stock_movements ORDER BY movement_id"
        )

    @patch("smartstock_pipeline.extract_stock_movements.connect")
    def test_empty_source_writes_header_only_csv(self, mock_connect: MagicMock) -> None:
        self.set_source_results(list(FIELDS), [])
        mock_connect.return_value = self.connection

        count = extract_stock_movements(self.output)

        self.assertEqual(count, 0)
        with self.output.open(encoding="utf-8", newline="") as csv_file:
            self.assertEqual(list(csv.reader(csv_file)), [list(FIELDS)])

    @patch("smartstock_pipeline.extract_stock_movements.connect")
    def test_missing_required_column_fails_without_creating_output(
        self, mock_connect: MagicMock
    ) -> None:
        self.set_source_results([field for field in FIELDS if field != "movement_date"], [])
        mock_connect.return_value = self.connection

        with self.assertRaisesRegex(ExtractionError, "movement_date"):
            extract_stock_movements(self.output)

        self.assertFalse(self.output.exists())
        self.assertEqual(self.connection.execute.call_count, 1)

    @patch("smartstock_pipeline.extract_stock_movements.connect")
    def test_duplicate_primary_keys_fail_without_creating_output(
        self, mock_connect: MagicMock
    ) -> None:
        row = (9, 4, "adjustment", 6, None, 75)
        self.set_source_results(list(FIELDS), [row, row])
        mock_connect.return_value = self.connection

        with self.assertRaisesRegex(ExtractionError, "duplicate movement_id"):
            extract_stock_movements(self.output)

        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
