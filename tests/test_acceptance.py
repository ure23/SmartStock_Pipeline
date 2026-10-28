from __future__ import annotations

import csv
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from smartstock_pipeline.acceptance import (
    ACCEPTANCE_FILE,
    APPROVED,
    HANDOVER_MARKER,
    MANUAL_REVIEW,
    REJECTED,
    decide_acceptance,
    record_acceptance,
    review_batch,
)
from smartstock_pipeline.validate_contract import CONTRACTS


class AcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.batch = Path(self.temp.name) / "batch"
        self.batch.mkdir(mode=0o700)
        os.chmod(self.batch, 0o700)
        self.run_id = "RUN-synthetic-test"
        log_dir = Path(self.temp.name) / "logs"
        log_dir.mkdir(mode=0o700)
        os.chmod(log_dir, 0o700)
        self.log_ref = str(log_dir / "synthetic.json")
        self._write_json(
            Path(self.log_ref),
            {
                "pipeline_run_id": self.run_id,
                "extraction_status": "SUCCESS",
                "validation_result": "PASS",
                "acceptance_status": MANUAL_REVIEW,
            },
        )
        self._write_json(
            self.batch / "extraction_metadata.json",
            {
                "pipeline_run_id": self.run_id,
                "validation_result": "PASS",
                "acceptance_status": MANUAL_REVIEW,
                "validation_warnings": ["products_materials.note: unexpected source column"],
                "log_ref": self.log_ref,
            },
        )
        self._write_contract_csvs()
        self._write_json(
            self.batch / ACCEPTANCE_FILE,
            {
                "pipeline_run_id": self.run_id,
                "acceptance_status": MANUAL_REVIEW,
                "validation_result": "PASS",
                "validation_warnings": ["products_materials.note: unexpected source column"],
                "reviewer": None,
                "review_note": None,
                "log_ref": self.log_ref,
                "metadata_ref": "extraction_metadata.json",
            },
        )

    def _write_json(self, path: Path, value: dict) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")
        os.chmod(path, 0o600)

    def _write_contract_csvs(self) -> None:
        for table, contract in CONTRACTS.items():
            path = self.batch / f"{table}.csv"
            with path.open("w", encoding="utf-8", newline="") as output:
                csv.writer(output, lineterminator="\n").writerow(contract.headers)
            os.chmod(path, 0o600)

    def test_acceptance_decision_fails_closed_and_holds_warnings(self) -> None:
        self.assertEqual(decide_acceptance(validation_passed=True), APPROVED)
        self.assertEqual(decide_acceptance(validation_passed=True, warnings=["review"]), MANUAL_REVIEW)
        self.assertEqual(decide_acceptance(validation_passed=False), REJECTED)

    def test_auto_approval_writes_approval_record_and_ready_marker(self) -> None:
        os.unlink(self.batch / ACCEPTANCE_FILE)
        manifest = json.loads((self.batch / "extraction_metadata.json").read_text())
        manifest["acceptance_status"] = APPROVED
        self._write_json(self.batch / "extraction_metadata.json", manifest)
        status = record_acceptance(
            self.batch,
            run_id=self.run_id,
            validation_passed=True,
            warnings=[],
            log_ref=self.log_ref,
        )
        self.assertEqual(status, APPROVED)
        acceptance = json.loads((self.batch / ACCEPTANCE_FILE).read_text())
        marker = json.loads((self.batch / HANDOVER_MARKER).read_text())
        self.assertEqual(acceptance["acceptance_status"], APPROVED)
        self.assertEqual(marker["acceptance_status"], APPROVED)
        self.assertEqual(marker["pipeline_run_id"], self.run_id)
        self.assertEqual(stat.S_IMODE((self.batch / HANDOVER_MARKER).stat().st_mode), 0o600)

    def test_warning_batch_is_held_until_reviewer_approves(self) -> None:
        status = record_acceptance(
            self.batch,
            run_id=self.run_id,
            validation_passed=True,
            warnings=["unexpected additional source column"],
            log_ref=self.log_ref,
        )
        self.assertEqual(status, MANUAL_REVIEW)
        self.assertFalse((self.batch / HANDOVER_MARKER).exists())

        result = review_batch(
            self.batch,
            decision=APPROVED,
            reviewer="synthetic-reviewer",
            note="Synthetic warning reviewed for integration coverage.",
        )
        self.assertEqual(result["acceptance_status"], APPROVED)
        self.assertEqual(json.loads((self.batch / ACCEPTANCE_FILE).read_text())["reviewer"], "synthetic-reviewer")
        marker = json.loads((self.batch / HANDOVER_MARKER).read_text())
        self.assertEqual(marker["pipeline_run_id"], self.run_id)

    def test_reviewer_can_reject_without_creating_handover_marker(self) -> None:
        result = review_batch(
            self.batch,
            decision=REJECTED,
            reviewer="synthetic-reviewer",
            note="Synthetic rejection-path test.",
        )
        self.assertEqual(result["acceptance_status"], REJECTED)
        self.assertFalse((self.batch / HANDOVER_MARKER).exists())
        record = json.loads((self.batch / ACCEPTANCE_FILE).read_text())
        self.assertEqual(record["acceptance_status"], REJECTED)
        self.assertEqual(record["review_note"], "Synthetic rejection-path test.")

    def test_invalid_or_incomplete_batch_cannot_be_approved(self) -> None:
        (self.batch / "orders.csv").unlink()
        with self.assertRaises(ValueError):
            review_batch(
                self.batch,
                decision=APPROVED,
                reviewer="synthetic-reviewer",
                note="Should be rejected because an output is missing.",
            )
        self.assertFalse((self.batch / HANDOVER_MARKER).exists())

    def test_reviewer_identity_and_note_are_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "identity and decision note"):
            review_batch(
                self.batch,
                decision=APPROVED,
                reviewer=" ",
                note=" ",
            )


if __name__ == "__main__":
    unittest.main()
