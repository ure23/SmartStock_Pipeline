from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from smartstock_pipeline.import_workbook_products import (
    REQUIRED_PRICE_LIST_COLUMNS,
    WorkbookMappingError,
    import_workbook_products,
)


def result(value=None, *, rows=None):
    mocked = MagicMock()
    mocked.fetchone.return_value = (value,)
    mocked.fetchall.return_value = rows or []
    return mocked


class WorkbookProductMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection

    @patch("smartstock_pipeline.import_workbook_products.connect")
    def test_product_import_creates_stable_map_and_returns_count(
        self, mock_connect: MagicMock
    ) -> None:
        mock_connect.return_value = self.connection
        self.connection.execute.side_effect = [
            result(rows=[(column,) for column in REQUIRED_PRICE_LIST_COLUMNS]),
            result(0),
            result(0),
            result(),
            result(0),
            result(),
            result(),
            result(359),
        ]

        count = import_workbook_products()

        self.assertEqual(count, 359)
        sql = [call.args[0] for call in self.connection.execute.call_args_list]
        self.assertTrue(any("product_id_map" in statement for statement in sql))
        self.assertTrue(any("ON CONFLICT (product_id)" in statement for statement in sql))
        self.assertTrue(any("lower(trim(product))" in statement for statement in sql))

    @patch("smartstock_pipeline.import_workbook_products.connect")
    def test_product_import_rejects_ambiguous_key_before_writes(
        self, mock_connect: MagicMock
    ) -> None:
        mock_connect.return_value = self.connection
        self.connection.execute.side_effect = [
            result(rows=[(column,) for column in REQUIRED_PRICE_LIST_COLUMNS]),
            result(0),
            result(1),
        ]

        with self.assertRaisesRegex(WorkbookMappingError, "ambiguous normalized product"):
            import_workbook_products()

        self.assertEqual(self.connection.execute.call_count, 3)


if __name__ == "__main__":
    unittest.main()
