from __future__ import annotations

import json
import io
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from pathlib import Path

from smartstock_pipeline.run_metadata import (
    ExtractionRun,
    RunMetadataError,
    prune_expired_logs,
)


class ExtractionRunMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.log_dir = Path(self.temp_dir.name) / "logs"

    def test_success_run_writes_restricted_metadata_and_counts(self) -> None:
        run = ExtractionRun(("products_materials",), log_dir=self.log_dir)
        with run:
            run.record_counts(
                "products_materials",
                records_read=12,
                records_extracted=12,
            )

        log_path = self.log_dir / f"{run.run_id}.json"
        metadata = json.loads(log_path.read_text(encoding="utf-8"))

        self.assertEqual(stat.S_IMODE(self.log_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(log_path.stat().st_mode), 0o600)
        self.assertEqual(metadata["pipeline_run_id"], run.run_id)
        self.assertEqual(metadata["table_names"], ["products_materials"])
        self.assertEqual(metadata["extraction_status"], "SUCCESS")
        self.assertEqual(metadata["validation_result"], "PASS")
        self.assertEqual(metadata["records_read"], 12)
        self.assertEqual(metadata["records_extracted"], 12)
        self.assertEqual(metadata["records_rejected"], 0)
        self.assertEqual(metadata["records"]["products_materials"]["records_read"], 12)
        self.assertIsNone(metadata["error_message"])
        self.assertTrue(metadata["start_timestamp"].endswith("Z"))
        self.assertTrue(metadata["end_timestamp"].endswith("Z"))

    def test_failure_log_suppresses_exception_details(self) -> None:
        run = ExtractionRun(("orders", "order_items"), log_dir=self.log_dir)
        with self.assertRaisesRegex(RuntimeError, "source value secret"):
            with run:
                raise RuntimeError("source value secret")

        metadata = json.loads(
            (self.log_dir / f"{run.run_id}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["extraction_status"], "FAILED")
        self.assertEqual(metadata["validation_result"], "FAIL")
        self.assertNotIn("source value secret", json.dumps(metadata))
        self.assertEqual(metadata["error_message"], "RuntimeError: details suppressed to protect source data")

    def test_retention_deletes_only_expired_successful_logs(self) -> None:
        self.log_dir.mkdir(mode=0o700)
        now = datetime(2026, 11, 18, tzinfo=timezone.utc)
        old_success = {
            "extraction_status": "SUCCESS",
            "end_timestamp": "2026-10-01T00:00:00Z",
        }
        failed = {
            "extraction_status": "FAILED",
            "end_timestamp": "2026-10-01T00:00:00Z",
        }
        fresh_success = {
            "extraction_status": "SUCCESS",
            "end_timestamp": "2026-11-01T00:00:00Z",
        }
        (self.log_dir / "old.json").write_text(json.dumps(old_success), encoding="utf-8")
        (self.log_dir / "failed.json").write_text(json.dumps(failed), encoding="utf-8")
        (self.log_dir / "fresh.json").write_text(json.dumps(fresh_success), encoding="utf-8")
        (self.log_dir / "unknown.json").write_text("not-json", encoding="utf-8")
        for path in self.log_dir.glob("*.json"):
            path.chmod(0o600)

        removed = prune_expired_logs(self.log_dir, now=now)

        self.assertEqual(removed, 1)
        self.assertFalse((self.log_dir / "old.json").exists())
        self.assertTrue((self.log_dir / "failed.json").exists())
        self.assertTrue((self.log_dir / "fresh.json").exists())
        self.assertTrue((self.log_dir / "unknown.json").exists())

    def test_insecure_log_directory_is_rejected(self) -> None:
        self.log_dir.mkdir(mode=0o755)
        self.log_dir.chmod(0o755)

        with self.assertRaisesRegex(RunMetadataError, "mode 0700"):
            with ExtractionRun(("inventory",), log_dir=self.log_dir):
                pass

    def test_exporter_cli_records_successful_run(self) -> None:
        from unittest.mock import patch

        from smartstock_pipeline.extract_products_materials import main

        with patch.dict(os.environ, {"SMARTSTOCK_LOG_DIR": str(self.log_dir)}):
            with patch(
                "smartstock_pipeline.extract_products_materials.extract_products_materials",
                return_value=3,
            ):
                result = main(["--output", str(Path(self.temp_dir.name) / "out.csv")])

        self.assertEqual(result, 0)
        logs = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(logs), 1)
        metadata = json.loads(logs[0].read_text(encoding="utf-8"))
        self.assertEqual(metadata["table_names"], ["products_materials"])
        self.assertEqual(metadata["records_read"], 3)
        self.assertEqual(metadata["records_extracted"], 3)

    def test_exporter_cli_records_failed_run_without_exception_details(self) -> None:
        from unittest.mock import patch

        from smartstock_pipeline.extract_products_materials import ExtractionError, main

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with patch.dict(os.environ, {"SMARTSTOCK_LOG_DIR": str(self.log_dir)}):
                with patch(
                    "smartstock_pipeline.extract_products_materials.extract_products_materials",
                    side_effect=ExtractionError("source row value must not be logged"),
                ):
                    result = main(["--output", str(Path(self.temp_dir.name) / "out.csv")])

        self.assertEqual(result, 1)
        self.assertNotIn("source row value", stderr.getvalue())
        logs = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(logs), 1)
        metadata = json.loads(logs[0].read_text(encoding="utf-8"))
        self.assertEqual(metadata["extraction_status"], "FAILED")
        self.assertNotIn("source row value", json.dumps(metadata))

    def test_retention_cannot_be_shorter_than_thirty_days(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 30 days"):
            prune_expired_logs(self.log_dir, retention_days=29)

    def test_counts_reject_unknown_tables_and_negative_values(self) -> None:
        run = ExtractionRun(("inventory",), log_dir=self.log_dir)
        with run:
            with self.assertRaisesRegex(ValueError, "not part"):
                run.record_counts("orders", records_read=0, records_extracted=0)
            with self.assertRaisesRegex(ValueError, "cannot be negative"):
                run.record_counts("inventory", records_read=-1, records_extracted=0)


if __name__ == "__main__":
    unittest.main()
