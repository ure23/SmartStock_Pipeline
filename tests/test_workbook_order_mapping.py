from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from smartstock_pipeline.import_workbook_orders import (
    ITEM_COLUMNS,
    TRACKER_COLUMNS,
    WorkbookMappingError,
    import_workbook_orders_and_items,
)


def result(value=None, *, rows=None):
    mocked = MagicMock()
    mocked.fetchone.return_value = (value,)
    mocked.fetchall.return_value = rows or []
    return mocked


class WorkbookOrderMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection

    @patch("smartstock_pipeline.import_workbook_orders.connect")
    def test_order_import_rejects_duplicate_natural_key_before_writes(
        self, mock_connect: MagicMock
    ) -> None:
        mock_connect.return_value = self.connection
        self.connection.execute.side_effect = [
            result(rows=[(column,) for column in TRACKER_COLUMNS]),
            result(rows=[(column,) for column in ITEM_COLUMNS]),
            result(True),
            result(0),
            result(1),
        ]

        with self.assertRaisesRegex(WorkbookMappingError, "ambiguous natural order key"):
            import_workbook_orders_and_items()

        self.assertEqual(self.connection.execute.call_count, 5)

    @patch("smartstock_pipeline.import_workbook_orders.connect")
    def test_order_import_widens_numeric_fields_and_reports_match_counts(
        self, mock_connect: MagicMock
    ) -> None:
        mock_connect.return_value = self.connection
        self.connection.execute.side_effect = [
            result(rows=[(column,) for column in TRACKER_COLUMNS]),
            result(rows=[(column,) for column in ITEM_COLUMNS]),
            result(True),
            result(0),
            result(0),
            result(0),
            result(0),
            result(),
            result(),
            result(),
            result(),
            result(),
            result(),
            result(0),
            result(0),
            result(),
            result(),
            result(),
            result(),
            result(),
            result(),
            result(493),
            result(1524),
            result(14),
        ]

        imported = import_workbook_orders_and_items()

        self.assertEqual(imported.orders, 493)
        self.assertEqual(imported.order_items, 1524)
        self.assertEqual(imported.quarantined_order_items, 14)
        sql = [call.args[0] for call in self.connection.execute.call_args_list]
        self.assertTrue(any("ALTER TABLE public.orders" in statement for statement in sql))
        self.assertTrue(any("ALTER TABLE public.order_items" in statement for statement in sql))
        self.assertTrue(any("ON CONFLICT (order_item_id)" in statement for statement in sql))
        self.assertTrue(any("pipeline_quarantine" in statement for statement in sql))


if __name__ == "__main__":
    unittest.main()
