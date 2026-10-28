"""Acceptance decisions and approval-gated Stage 1 handover markers."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from smartstock_pipeline.db import DatabaseConfig, connect
from smartstock_pipeline.validate_contract import (
    CONTRACTS,
    validate_csv,
    validate_foreign_key_rows,
)

APPROVED = "APPROVED"
MANUAL_REVIEW = "MANUAL REVIEW"
REJECTED = "REJECTED"
ACCEPTANCE_FILE = "acceptance.json"
HANDOVER_MARKER = "handover_ready.json"
MANIFEST_FILE = "extraction_metadata.json"


def decide_acceptance(*, validation_passed: bool, warnings: Sequence[str] = ()) -> str:
    """Fail closed on critical validation failures; hold warnings for review."""
    if not validation_passed:
        return REJECTED
    if warnings:
        return MANUAL_REVIEW
    return APPROVED


def _secure_batch_directory(path: Path) -> Path:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("Batch path must be a real directory")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("Batch directory must be owner-only mode 0700")
    return path


def _atomic_json(path: Path, payload: dict) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def verify_success_log(log_ref: str, run_id: str) -> None:
    if not isinstance(log_ref, str) or not log_ref:
        raise ValueError("Successful extraction log reference is missing")
    log_path = Path(log_ref)
    try:
        info = log_path.lstat()
        parent_info = log_path.parent.lstat()
    except FileNotFoundError as exc:
        raise ValueError("Successful extraction log is missing") from exc
    if (not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode)
            or parent_info.st_uid != os.getuid() or stat.S_IMODE(parent_info.st_mode) != 0o700):
        raise ValueError("Successful extraction log directory must be owner-only mode 0700")
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
        raise ValueError("Successful extraction log must be a regular owner-only mode-0600 file")
    try:
        log = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Successful extraction log is unreadable") from exc
    if (log.get("pipeline_run_id") != run_id
            or log.get("extraction_status") != "SUCCESS"
            or log.get("validation_result") != "PASS"
            or log.get("acceptance_status") not in {APPROVED, MANUAL_REVIEW}):
        raise ValueError("Successful extraction log does not match the accepted run")


def write_handover_marker(batch_dir: Path, run_id: str) -> None:
    directory = _secure_batch_directory(batch_dir)
    acceptance_path = directory / ACCEPTANCE_FILE
    manifest_path = directory / MANIFEST_FILE
    for path in (acceptance_path, manifest_path):
        try:
            info = path.lstat()
        except FileNotFoundError as exc:
            raise ValueError("Approved handover metadata is missing") from exc
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError("Approved handover metadata must be owner-only mode-0600 files")
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (acceptance.get("pipeline_run_id") != run_id
            or acceptance.get("acceptance_status") != APPROVED
            or manifest.get("pipeline_run_id") != run_id
            or manifest.get("validation_result") != "PASS"
            or manifest.get("acceptance_status") != APPROVED
            or acceptance.get("log_ref") != manifest.get("log_ref")):
        raise ValueError("Only an approved, validated batch can receive a handover marker")
    verify_success_log(acceptance.get("log_ref"), run_id)
    _atomic_json(
        directory / HANDOVER_MARKER,
        {
            "pipeline_run_id": run_id,
            "acceptance_status": APPROVED,
            "handover_status": APPROVED,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
    )


def record_acceptance(
    batch_dir: str | Path,
    *,
    run_id: str,
    validation_passed: bool,
    warnings: Sequence[str],
    log_ref: str,
    write_marker: bool = True,
) -> str:
    """Write the acceptance record; publish a marker only for auto-approved data."""
    directory = Path(batch_dir)
    _secure_batch_directory(directory)
    status = decide_acceptance(validation_passed=validation_passed, warnings=warnings)
    record = {
        "pipeline_run_id": run_id,
        "acceptance_status": status,
        "validation_result": "PASS" if validation_passed else "FAIL",
        "validation_warnings": list(warnings),
        "reviewer": None,
        "review_note": None,
        "log_ref": log_ref,
        "metadata_ref": MANIFEST_FILE,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _atomic_json(directory / ACCEPTANCE_FILE, record)
    if status == APPROVED and write_marker:
        write_handover_marker(directory, run_id)
    return status


def _verify_batch_contract(batch_dir: Path, run_id: str) -> list[str]:
    manifest_path = batch_dir / MANIFEST_FILE
    info = manifest_path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("Batch metadata is not a regular file")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("Batch metadata must be owner-only mode 0600")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("pipeline_run_id") != run_id or manifest.get("validation_result") != "PASS":
        raise ValueError("Batch metadata does not identify a successfully validated run")
    verify_success_log(manifest.get("log_ref"), run_id)

    paths: dict[str, Path] = {}
    for table in CONTRACTS:
        path = batch_dir / f"{table}.csv"
        try:
            file_info = path.lstat()
        except FileNotFoundError as exc:
            raise ValueError("A required CSV is missing") from exc
        if not stat.S_ISREG(file_info.st_mode) or stat.S_ISLNK(file_info.st_mode):
            raise ValueError("A required CSV is missing or is not a regular file")
        if file_info.st_uid != os.getuid() or stat.S_IMODE(file_info.st_mode) != 0o600:
            raise ValueError("Handover CSVs must be owner-only mode 0600")
        _count, errors = validate_csv(path, table)
        if errors:
            raise ValueError("Batch CSV validation failed; approval denied")
        paths[table] = path
    if manifest.get("baseline") is False and manifest.get("extraction_window") != "full_snapshot":
        if manifest.get("full_snapshot_relationship_validation") != "PASS":
            raise ValueError("Incremental batch lacks full-snapshot relationship validation evidence")
    else:
        fk_errors = validate_foreign_key_rows(paths)
        if fk_errors:
            raise ValueError("Batch relationship validation failed; approval denied")
    return list(manifest.get("validation_warnings", []))


def _finalize_incremental_review(
    manifest: dict,
    *,
    decision: str,
    config: DatabaseConfig | None,
) -> None:
    if "baseline" not in manifest or manifest.get("extraction_window") == "full_snapshot":
        return
    if config is None:
        raise ValueError("Incremental review requires the configured Pipeline database")

    run_id = manifest["pipeline_run_id"]
    previous_run_id = manifest.get("previous_successful_run_id")
    lock_id = 73194621058421
    with connect(config) as connection:
        with connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))
            watermark = connection.execute(
                "SELECT last_successful_run_id FROM pipeline_extraction_watermark "
                "WHERE singleton=TRUE FOR UPDATE"
            ).fetchone()
            current_run_id = watermark[0] if watermark else None
            pending = connection.execute(
                "SELECT 1 FROM pipeline_extraction_pending_run WHERE run_id=%s",
                (run_id,),
            ).fetchone()

            if decision == APPROVED and current_run_id == run_id:
                return  # Marker recovery after an already committed approval.
            if current_run_id != previous_run_id:
                raise ValueError("Pipeline watermark changed since this review batch was created")
            if decision == REJECTED:
                if pending:
                    connection.execute(
                        "DELETE FROM pipeline_extraction_pending_run WHERE run_id=%s",
                        (run_id,),
                    )
                return
            if not pending:
                raise ValueError("Incremental review candidate state is missing")

            connection.execute("DELETE FROM pipeline_extraction_row_state")
            connection.execute(
                "INSERT INTO pipeline_extraction_row_state (table_name, record_key, content_sha256) "
                "SELECT table_name, record_key, content_sha256 "
                "FROM pipeline_extraction_pending_row_state WHERE run_id=%s",
                (run_id,),
            )
            connection.execute(
                """INSERT INTO pipeline_extraction_watermark
                    (singleton, last_successful_run_id, last_successful_at)
                    VALUES (TRUE, %s, %s)
                    ON CONFLICT (singleton) DO UPDATE SET
                        last_successful_run_id=EXCLUDED.last_successful_run_id,
                        last_successful_at=EXCLUDED.last_successful_at""",
                (run_id, datetime.now(timezone.utc)),
            )
            connection.execute(
                "DELETE FROM pipeline_extraction_pending_run WHERE run_id=%s",
                (run_id,),
            )


def review_batch(
    batch_dir: str | Path,
    *,
    decision: str,
    reviewer: str,
    note: str,
    config: DatabaseConfig | None = None,
) -> dict[str, str]:
    """Record an authorized human decision for a MANUAL REVIEW batch."""
    if decision not in {APPROVED, REJECTED}:
        raise ValueError("Manual review decision must be APPROVED or REJECTED")
    reviewer = reviewer.strip()
    note = note.strip()
    if not reviewer or not note:
        raise ValueError("Reviewer identity and decision note are required")

    directory = Path(batch_dir).expanduser().absolute()
    _secure_batch_directory(directory)
    acceptance_path = directory / ACCEPTANCE_FILE
    acceptance_info = acceptance_path.lstat()
    if (not stat.S_ISREG(acceptance_info.st_mode) or stat.S_ISLNK(acceptance_info.st_mode)
            or acceptance_info.st_uid != os.getuid()
            or stat.S_IMODE(acceptance_info.st_mode) != 0o600):
        raise ValueError("Acceptance record must be a regular owner-only mode-0600 file")
    record = json.loads(acceptance_path.read_text(encoding="utf-8"))
    manifest_path = directory / MANIFEST_FILE
    try:
        manifest_info = manifest_path.lstat()
    except FileNotFoundError as exc:
        raise ValueError("Batch metadata is missing") from exc
    if (not stat.S_ISREG(manifest_info.st_mode) or stat.S_ISLNK(manifest_info.st_mode)
            or manifest_info.st_uid != os.getuid()
            or stat.S_IMODE(manifest_info.st_mode) != 0o600):
        raise ValueError("Batch metadata must be a regular owner-only mode-0600 file")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_id = record.get("pipeline_run_id")
    if (not isinstance(run_id, str) or not run_id
            or manifest.get("pipeline_run_id") != run_id
            or manifest.get("validation_result") != "PASS"
            or record.get("log_ref") != manifest.get("log_ref")):
        raise ValueError("Batch metadata does not identify the validated acceptance record")
    marker_path = directory / HANDOVER_MARKER
    if marker_path.exists() or marker_path.is_symlink():
        raise ValueError("A manual-review batch must not already be handover-ready")
    if record.get("acceptance_status") not in {MANUAL_REVIEW, APPROVED, REJECTED}:
        raise ValueError("Batch is not in a reviewable acceptance state")
    if record.get("acceptance_status") in {APPROVED, REJECTED} and not (
        record.get("reviewer") == reviewer and record.get("review_note") == note
        and record.get("acceptance_status") == decision
    ):
        raise ValueError("A final human decision cannot be overwritten")

    if decision == APPROVED:
        _verify_batch_contract(directory, run_id)

    recorded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    final_record = {
        **record,
        "acceptance_status": decision,
        "reviewer": reviewer,
        "review_note": note,
        "recorded_at": recorded_at,
    }
    final_manifest = {
        **manifest,
        "acceptance_status": decision,
        "reviewer": reviewer,
        "review_note": note,
        "acceptance_recorded_at": recorded_at,
    }
    _atomic_json(acceptance_path, final_record)
    _atomic_json(manifest_path, final_manifest)
    if "baseline" in manifest and manifest.get("extraction_window") != "full_snapshot":
        _finalize_incremental_review(
            manifest,
            decision=decision,
            config=config or DatabaseConfig.from_env(),
        )
    if decision == APPROVED:
        write_handover_marker(directory, run_id)
    return {"pipeline_run_id": run_id, "acceptance_status": decision}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record a final human decision for a Stage 1 review batch.")
    parser.add_argument("--batch-dir", required=True)
    parser.add_argument("--decision", choices=(APPROVED, REJECTED), required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--note", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        review_config = None
        manifest_path = Path(args.batch_dir).expanduser() / MANIFEST_FILE
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if "baseline" in manifest and manifest.get("extraction_window") != "full_snapshot":
                # Reuse the scheduled runner's owner-only .env validation rather than
                # parsing database secrets independently in this command.
                from smartstock_pipeline.scheduled_runner import _load_database_environment

                _load_database_environment(Path(__file__).resolve().parent.parent / ".env")
                review_config = DatabaseConfig.from_env()
        result = review_batch(
            args.batch_dir,
            decision=args.decision,
            reviewer=args.reviewer,
            note=args.note,
            config=review_config,
        )
    except Exception as exc:
        print(f"Acceptance review failed: {type(exc).__name__}; details suppressed", file=sys.stderr)
        return 1
    print(f"Recorded acceptance {result['acceptance_status']} for {result['pipeline_run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
