from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from smartstock_pipeline.extract_orders import (
    ORDER_ITEMS_FIELDS,
    ORDERS_FIELDS,
    ExtractionError,
    extract_orders_and_items,
)


class OrdersExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.orders_output = root / "orders.csv"
        self.items_output = root / "order_items.csv"
        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection

    def set_source_results(
        self,
        orders_columns: list[str] | None = None,
        orders_rows: list[tuple] | None = None,
        items_columns: list[str] | None = None,
        items_rows: list[tuple] | None = None,
    ) -> None:
        def result(rows):
            mocked = MagicMock()
            mocked.fetchall.return_value = rows
            return mocked

        self.connection.execute.side_effect = [
            MagicMock(),
            result([(column,) for column in orders_columns or ORDERS_FIELDS]),
            result(orders_rows or []),
            result([(column,) for column in items_columns or ORDER_ITEMS_FIELDS]),
            result(items_rows or []),
        ]

    @patch("smartstock_pipeline.extract_orders.connect")
    def test_exports_both_tables_and_preserves_order_id(self, mock_connect: MagicMock) -> None:
        order = (51, 8, date(2026, 10, 6), "complete", Decimal("24.50"))
        item = (901, 51, 7, 2, Decimal("12.25"))
        self.set_source_results(orders_rows=[order], items_rows=[item])
        mock_connect.return_value = self.connection

        counts = extract_orders_and_items(self.orders_output, self.items_output)

        self.assertEqual(counts, (1, 1))
        with self.orders_output.open(encoding="utf-8", newline="") as f:
            orders_csv = list(csv.reader(f))
        with self.items_output.open(encoding="utf-8", newline="") as f:
            items_csv = list(csv.reader(f))
        self.assertEqual(orders_csv[0], list(ORDERS_FIELDS))
        self.assertEqual(orders_csv[1], ["51", "8", "2026-10-06", "complete", "24.50"])
        self.assertEqual(items_csv[0], list(ORDER_ITEMS_FIELDS))
        self.assertEqual(items_csv[1], ["901", "51", "7", "2", "12.25"])
        self.assertIn("order_id", orders_csv[0])
        self.assertIn("order_id", items_csv[0])
        self.assertEqual(
            self.connection.execute.call_args_list[0].args[0],
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        )

    @patch("smartstock_pipeline.extract_orders.connect")
    def test_empty_sources_write_both_headers(self, mock_connect: MagicMock) -> None:
        self.set_source_results()
        mock_connect.return_value = self.connection

        counts = extract_orders_and_items(self.orders_output, self.items_output)

        self.assertEqual(counts, (0, 0))
        with self.orders_output.open(encoding="utf-8", newline="") as f:
            self.assertEqual(list(csv.reader(f)), [list(ORDERS_FIELDS)])
        with self.items_output.open(encoding="utf-8", newline="") as f:
            self.assertEqual(list(csv.reader(f)), [list(ORDER_ITEMS_FIELDS)])

    @patch("smartstock_pipeline.extract_orders.connect")
    def test_missing_required_column_fails_before_output(self, mock_connect: MagicMock) -> None:
        self.set_source_results(orders_columns=[f for f in ORDERS_FIELDS if f != "status"])
        mock_connect.return_value = self.connection

        with self.assertRaisesRegex(ExtractionError, "status"):
            extract_orders_and_items(self.orders_output, self.items_output)

        self.assertFalse(self.orders_output.exists())
        self.assertFalse(self.items_output.exists())

    @patch("smartstock_pipeline.extract_orders.connect")
    def test_duplicate_primary_key_fails_before_output(self, mock_connect: MagicMock) -> None:
        order = (51, 8, date(2026, 10, 6), "complete", Decimal("24.50"))
        self.set_source_results(orders_rows=[order, order])
        mock_connect.return_value = self.connection

        with self.assertRaisesRegex(ExtractionError, "duplicate order_id"):
            extract_orders_and_items(self.orders_output, self.items_output)

        self.assertFalse(self.orders_output.exists())
        self.assertFalse(self.items_output.exists())

    @patch("smartstock_pipeline.extract_orders.connect")
    def test_missing_order_item_column_fails_before_output(self, mock_connect: MagicMock) -> None:
        self.set_source_results(
            items_columns=[field for field in ORDER_ITEMS_FIELDS if field != "order_id"]
        )
        mock_connect.return_value = self.connection

        with self.assertRaisesRegex(ExtractionError, "order_id"):
            extract_orders_and_items(self.orders_output, self.items_output)

        self.assertFalse(self.orders_output.exists())
        self.assertFalse(self.items_output.exists())

    @patch("smartstock_pipeline.extract_orders.connect")
    def test_duplicate_order_item_primary_key_fails_before_output(
        self, mock_connect: MagicMock
    ) -> None:
        item = (901, 51, 7, 2, Decimal("12.25"))
        self.set_source_results(items_rows=[item, item])
        mock_connect.return_value = self.connection

        with self.assertRaisesRegex(ExtractionError, "duplicate order_item_id"):
            extract_orders_and_items(self.orders_output, self.items_output)

        self.assertFalse(self.orders_output.exists())
        self.assertFalse(self.items_output.exists())

    @patch("smartstock_pipeline.extract_orders.connect")
    def test_output_paths_must_be_different(self, mock_connect: MagicMock) -> None:
        with self.assertRaisesRegex(ExtractionError, "different files"):
            extract_orders_and_items(self.orders_output, self.orders_output)
        mock_connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
