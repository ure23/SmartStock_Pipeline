from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smartstock_pipeline.run_pipeline import OUTPUT_NAMES, run_pipeline
from smartstock_pipeline.validate_contract import ContractValidationError


class RunPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "handover"
        self.log_dir = self.root / "logs"
        self.env = patch.dict(os.environ, {"SMARTSTOCK_LOG_DIR": str(self.log_dir)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def _write(self, path: Path, count: int) -> int:
        path.write_text("header\n" + "row\n" * count, encoding="utf-8")
        return count

    def _export_patches(self):
        counts = {
            "products_materials": 2,
            "inventory": 0,
            "orders": 1,
            "order_items": 3,
            "stock_movements": 0,
        }
        return counts, (
            patch(
                "smartstock_pipeline.run_pipeline.extract_products_materials",
                side_effect=lambda path, _config=None: self._write(path, counts["products_materials"]),
            ),
            patch(
                "smartstock_pipeline.run_pipeline.extract_inventory",
                side_effect=lambda path: self._write(path, counts["inventory"]),
            ),
            patch(
                "smartstock_pipeline.run_pipeline.extract_orders_and_items",
                side_effect=lambda orders, items, _config=None: (
                    self._write(orders, counts["orders"]),
                    self._write(items, counts["order_items"]),
                ),
            ),
            patch(
                "smartstock_pipeline.run_pipeline.extract_stock_movements",
                side_effect=lambda path: self._write(path, counts["stock_movements"]),
            ),
        )

    def test_validated_batch_is_published_atomically_with_restricted_modes(self) -> None:
        counts, patches = self._export_patches()
        with patches[0], patches[1], patches[2], patches[3], patch(
            "smartstock_pipeline.run_pipeline.validate_outputs", return_value=counts.copy()
        ), patch("smartstock_pipeline.run_pipeline.connect"):
            self.assertEqual(run_pipeline(self.output), counts)

        self.assertEqual(set(path.name for path in self.output.iterdir()), set(OUTPUT_NAMES.values()))
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        for path in self.output.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.log_dir.stat().st_mode), 0o700)
        logs = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(logs), 1)
        self.assertEqual(json.loads(logs[0].read_text())["extraction_status"], "SUCCESS")
        self.assertFalse(list(self.root.glob(".handover.stage-*")))

    def test_extraction_failure_never_publishes_partial_files(self) -> None:
        _, patches = self._export_patches()
        with patches[0], patch(
            "smartstock_pipeline.run_pipeline.extract_inventory",
            side_effect=RuntimeError("sensitive source detail"),
        ), patches[2], patches[3], patch(
            "smartstock_pipeline.run_pipeline.validate_outputs"
        ) as validate, patch("smartstock_pipeline.run_pipeline.connect"):
            with self.assertRaises(RuntimeError):
                run_pipeline(self.output)
        validate.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob(".handover.stage-*")))
        metadata = json.loads(next(self.log_dir.glob("*.json")).read_text())
        self.assertEqual(metadata["extraction_status"], "FAILED")
        self.assertNotIn("sensitive source detail", json.dumps(metadata))

    def test_validation_failure_never_publishes_batch(self) -> None:
        counts, patches = self._export_patches()
        validation_error = ContractValidationError(["inventory: row count mismatch"], counts)
        with patches[0], patches[1], patches[2], patches[3], patch(
            "smartstock_pipeline.run_pipeline.validate_outputs", side_effect=validation_error
        ), patch("smartstock_pipeline.run_pipeline.connect"):
            with self.assertRaises(ContractValidationError):
                run_pipeline(self.output)

        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob(".handover.stage-*")))
        metadata = json.loads(next(self.log_dir.glob("*.json")).read_text())
        self.assertEqual(metadata["validation_result"], "FAIL")
        self.assertEqual(metadata["validation_errors"], ["inventory: row count mismatch"])

    def test_existing_output_is_not_overwritten(self) -> None:
        self.output.mkdir(mode=0o700)
        sentinel = self.output / "keep.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        with patch("smartstock_pipeline.run_pipeline.extract_products_materials") as extract:
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                run_pipeline(self.output)
        extract.assert_not_called()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
