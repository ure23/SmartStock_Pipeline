from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal

from smartstock_pipeline.incremental_pipeline import (
    _record_hash,
    _record_key,
    _validate_snapshot_relationships,
)
from smartstock_pipeline.validate_contract import CONTRACTS


class IncrementalSnapshotTests(unittest.TestCase):
    def test_row_hash_is_stable_and_changes_when_any_contract_value_changes(self) -> None:
        row = (7, "Glass", "Sheet", Decimal("12.50"), 2, "ACTIVE", None)
        self.assertEqual(_record_hash(row), _record_hash(tuple(row)))
        changed = (7, "Glass", "Sheet", Decimal("12.51"), 2, "ACTIVE", None)
        self.assertNotEqual(_record_hash(row), _record_hash(changed))

    def test_hash_normalizes_dates_and_decimal_without_float_conversion(self) -> None:
        first = (date(2026, 11, 18), datetime(2026, 11, 18, 2, 3, 4), Decimal("0.10"))
        second = (date(2026, 11, 18), datetime(2026, 11, 18, 2, 3, 4), Decimal("0.10"))
        self.assertEqual(_record_hash(first), _record_hash(second))
        self.assertNotEqual(_record_hash(first), _record_hash((first[0], first[1], Decimal("0.1"))))

    def test_primary_key_is_serialized_stably(self) -> None:
        contract = CONTRACTS["products_materials"]
        row = (12, "Item", "Glass", Decimal("1.00"), 0, "ACTIVE", None)
        self.assertEqual(_record_key(row, contract.headers, contract.primary_key), "[12]")

    def test_relationship_validation_checks_full_snapshot_without_exposing_keys(self) -> None:
        snapshot = {table: [] for table in CONTRACTS}
        snapshot["products_materials"] = [
            (1, "Synthetic", "Glass", Decimal("1.00"), 0, "ACTIVE", None)
        ]
        snapshot["inventory"] = [(10, 1, 3, 0, None)]
        snapshot["orders"] = [(20, 2, date(2026, 11, 18), "OPEN", Decimal("3.00"))]
        snapshot["order_items"] = [(30, 20, 1, Decimal("3"), Decimal("1.00"))]
        snapshot["stock_movements"] = [(40, 1, "IN", 3, datetime(2026, 11, 18), None)]
        self.assertEqual(_validate_snapshot_relationships(snapshot), [])

        snapshot["order_items"] = [(30, 999, 888, Decimal("3"), Decimal("1.00"))]
        errors = _validate_snapshot_relationships(snapshot)
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("order_items" in error for error in errors))
        self.assertNotIn("999", " ".join(errors))
        self.assertNotIn("888", " ".join(errors))


if __name__ == "__main__":
    unittest.main()
