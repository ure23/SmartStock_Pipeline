"""Incremental state-diff extraction for sources without reliable update times."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from smartstock_pipeline.acceptance import (
    APPROVED,
    HANDOVER_MARKER,
    decide_acceptance,
    record_acceptance,
    verify_success_log,
    write_handover_marker,
)
from smartstock_pipeline.db import (
    DatabaseConfig,
    DatabaseConfigurationError,
    DatabaseConnectionError,
    connect,
)
from smartstock_pipeline.run_metadata import ExtractionRun, RunMetadataError, safe_error_summary
from smartstock_pipeline.run_pipeline import OUTPUT_NAMES, PipelineError
from smartstock_pipeline.validate_contract import (
    CONTRACTS,
    ContractValidationError,
    validate_csv,
    validate_database_contract_report,
)

STATE_TABLE = "pipeline_extraction_row_state"
WATERMARK_TABLE = "pipeline_extraction_watermark"
PENDING_RUN_TABLE = "pipeline_extraction_pending_run"
PENDING_STATE_TABLE = "pipeline_extraction_pending_row_state"
ADVISORY_LOCK_ID = 73194621058421
DELETIONS_HEADER = ("table_name", "record_id")


class IncrementalPipelineError(RuntimeError):
    """Raised when a snapshot diff cannot be safely validated or published."""


def _normalized(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _record_hash(row: tuple) -> str:
    encoded = json.dumps(
        [_normalized(value) for value in row],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _record_key(row: tuple, headers: tuple[str, ...], primary_key: tuple[str, ...]) -> str:
    key = [row[headers.index(field)] for field in primary_key]
    return json.dumps([_normalized(value) for value in key], separators=(",", ":"))


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree_files(directory: Path) -> None:
    for path in directory.iterdir():
        if not path.is_file() or path.is_symlink():
            raise IncrementalPipelineError("Staging directory contains an unexpected entry")
        with path.open("rb") as source:
            os.fsync(source.fileno())
    _fsync_directory(directory)


def _write_csv(path: Path, headers: tuple[str, ...], rows: list[tuple]) -> None:
    with path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)
    os.chmod(path, 0o600)


def _write_deletions(path: Path, deletions: list[tuple[str, str]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(DELETIONS_HEADER)
        writer.writerows(deletions)
    os.chmod(path, 0o600)


def _ensure_state_tables(connection) -> None:
    connection.execute(
        f"""CREATE TABLE IF NOT EXISTS {WATERMARK_TABLE} (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
            last_successful_run_id TEXT NOT NULL,
            last_successful_at TIMESTAMPTZ NOT NULL
        )"""
    )
    connection.execute(
        f"""CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
            table_name TEXT NOT NULL,
            record_key TEXT NOT NULL,
            content_sha256 CHAR(64) NOT NULL,
            PRIMARY KEY (table_name, record_key)
        )"""
    )
    connection.execute(
        f"""CREATE TABLE IF NOT EXISTS {PENDING_RUN_TABLE} (
            run_id TEXT PRIMARY KEY,
            previous_run_id TEXT,
            completed_at TIMESTAMPTZ NOT NULL
        )"""
    )
    connection.execute(
        f"""CREATE TABLE IF NOT EXISTS {PENDING_STATE_TABLE} (
            run_id TEXT NOT NULL REFERENCES {PENDING_RUN_TABLE}(run_id) ON DELETE CASCADE,
            table_name TEXT NOT NULL,
            record_key TEXT NOT NULL,
            content_sha256 CHAR(64) NOT NULL,
            PRIMARY KEY (run_id, table_name, record_key)
        )"""
    )


def _load_state(connection) -> tuple[str | None, dict[str, dict[str, str]]]:
    watermark = connection.execute(
        f"SELECT last_successful_run_id FROM {WATERMARK_TABLE} WHERE singleton = TRUE"
    ).fetchone()
    previous_run_id = watermark[0] if watermark else None
    rows = connection.execute(
        f"SELECT table_name, record_key, content_sha256 FROM {STATE_TABLE}"
    ).fetchall()
    state: dict[str, dict[str, str]] = {table: {} for table in CONTRACTS}
    for table_name, record_key, content_hash in rows:
        if table_name in state:
            state[table_name][record_key] = content_hash.strip()
    return previous_run_id, state


def _recover_committed_handover(parent: Path, run_id: str | None) -> None:
    """Complete marker publication after a crash following DB state commit."""
    if run_id is None:
        return
    try:
        parent_info = parent.lstat()
    except OSError:
        return
    if (not parent.is_dir() or parent.is_symlink() or parent_info.st_uid != os.getuid()
            or parent_info.st_mode & 0o077):
        return
    for directory in parent.glob("batch-*"):
        if directory.is_symlink() or not directory.is_dir():
            continue
        directory_info = directory.lstat()
        if directory_info.st_uid != os.getuid() or directory_info.st_mode & 0o077:
            continue
        manifest_path = directory / "extraction_metadata.json"
        acceptance_path = directory / "acceptance.json"
        marker_path = directory / HANDOVER_MARKER
        if marker_path.exists() or marker_path.is_symlink():
            continue
        try:
            manifest_info = manifest_path.lstat()
            acceptance_info = acceptance_path.lstat()
            if (not manifest_path.is_file() or manifest_path.is_symlink()
                    or manifest_info.st_uid != os.getuid() or manifest_info.st_mode & 0o077
                    or not acceptance_path.is_file() or acceptance_path.is_symlink()
                    or acceptance_info.st_uid != os.getuid() or acceptance_info.st_mode & 0o077):
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
            verify_success_log(manifest.get("log_ref"), run_id)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
        if (manifest.get("pipeline_run_id") == run_id
                and manifest.get("validation_result") == "PASS"
                and manifest.get("acceptance_status") == APPROVED
                and acceptance.get("pipeline_run_id") == run_id
                and acceptance.get("acceptance_status") == APPROVED
                and acceptance.get("log_ref") == manifest.get("log_ref")):
            write_handover_marker(directory, run_id)


def _validate_snapshot_relationships(snapshot: dict[str, list[tuple]]) -> list[str]:
    primary_values: dict[str, set[str]] = {}
    for table_name, contract in CONTRACTS.items():
        primary_indexes = tuple(contract.headers.index(name) for name in contract.primary_key)
        primary_values[table_name] = {
            json.dumps(
                [_normalized(row[index]) for index in primary_indexes],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            for row in snapshot[table_name]
        }

    errors: list[str] = []
    for table_name, contract in CONTRACTS.items():
        for field_name, referenced_table, referenced_field in contract.foreign_keys:
            field_index = contract.headers.index(field_name)
            for row_number, row in enumerate(snapshot[table_name], start=2):
                value = row[field_index]
                if value is None:
                    continue
                reference = json.dumps(
                    [_normalized(value)], ensure_ascii=False, separators=(",", ":")
                )
                if reference not in primary_values[referenced_table]:
                    errors.append(
                        f"{table_name}: source row {row_number} has an unresolved foreign key in {field_name}"
                    )
    return errors


def run_incremental_pipeline(
    output_dir: str | Path,
    config: DatabaseConfig | None = None,
) -> dict[str, object]:
    """Publish changed rows and deletion tombstones; advance state on success.

    Every run reads one repeatable-read source snapshot and compares stable
    primary keys plus SHA-256 hashes with the last successfully published
    snapshot. The initial run is a complete baseline. Later CSVs contain only
    new/changed rows; ``deletions.csv`` carries removed-key tombstones. Source
    rows are scanned each run because verified row-modified timestamps are not
    available; unchanged rows are not re-exported.
    """
    requested = Path(output_dir).expanduser().absolute()
    requested.parent.mkdir(parents=True, exist_ok=True)
    destination = requested.parent.resolve() / requested.name
    if destination.exists() or destination.is_symlink():
        raise PipelineError("Output directory already exists; refusing to overwrite it")
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.stage-", dir=destination.parent))
    published = False
    state_committed = False
    control = None
    run: ExtractionRun | None = None
    previous_run_id: str | None = None
    source_counts: dict[str, int] = {}
    current_state: dict[str, dict[str, str]] = {table: {} for table in CONTRACTS}
    changed_rows: dict[str, list[tuple]] = {}
    deletion_rows: list[tuple[str, str]] = []
    validation_warnings: list[str] = []
    acceptance_status = "REJECTED"

    try:
        control = connect(config)
        control.autocommit = True
        locked = control.execute(
            "SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_ID,)
        ).fetchone()[0]
        if not locked:
            raise IncrementalPipelineError("Another incremental extraction is already running")
        _ensure_state_tables(control)
        previous_run_id, old_state = _load_state(control)
        pending_review = control.execute(
            f"SELECT run_id FROM {PENDING_RUN_TABLE} LIMIT 1"
        ).fetchone()
        if pending_review:
            raise IncrementalPipelineError(
                "An incremental batch is awaiting manual acceptance; resolve it before the next run"
            )
        _recover_committed_handover(destination.parent, previous_run_id)
        run = ExtractionRun(
            tuple(CONTRACTS),
            extraction_window=(
                "initial_baseline" if previous_run_id is None
                else f"content_changes_since:{previous_run_id}"
            ),
        )

        with run:
            with connect(config) as source:
                source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                schema_errors, validation_warnings = validate_database_contract_report(source)
                if validation_warnings:
                    run.record_validation_warnings(validation_warnings)
                if schema_errors:
                    run.record_validation_errors(schema_errors)
                    raise ContractValidationError(schema_errors)

                snapshot: dict[str, list[tuple]] = {}
                for table_name, contract in CONTRACTS.items():
                    fields_sql = ", ".join(contract.headers)
                    primary_sql = ", ".join(contract.primary_key)
                    snapshot[table_name] = source.execute(
                        f"SELECT {fields_sql} FROM {table_name} ORDER BY {primary_sql}"
                    ).fetchall()

            relationship_errors = _validate_snapshot_relationships(snapshot)
            if relationship_errors:
                run.record_validation_errors(relationship_errors)
                raise ContractValidationError(relationship_errors)

            changed_rows = {table: [] for table in CONTRACTS}
            deletion_rows: list[tuple[str, str]] = []
            source_counts: dict[str, int] = {}
            for table_name, contract in CONTRACTS.items():
                rows = snapshot[table_name]
                source_counts[table_name] = len(rows)
                for row in rows:
                    key = _record_key(row, contract.headers, contract.primary_key)
                    digest = _record_hash(row)
                    current_state[table_name][key] = digest
                    if old_state[table_name].get(key) != digest:
                        changed_rows[table_name].append(row)
                for missing_key in sorted(set(old_state[table_name]) - set(current_state[table_name])):
                    decoded_key = json.loads(missing_key)
                    record_id = ",".join(str(value) for value in decoded_key)
                    deletion_rows.append((table_name, record_id))
                run.record_counts(
                    table_name,
                    records_read=len(rows),
                    records_extracted=len(changed_rows[table_name]),
                )

            output_paths = {
                table: stage / OUTPUT_NAMES[table]
                for table in CONTRACTS
            }
            for table_name, contract in CONTRACTS.items():
                _write_csv(output_paths[table_name], contract.headers, changed_rows[table_name])
                actual_count, errors = validate_csv(output_paths[table_name], table_name)
                if actual_count != len(changed_rows[table_name]):
                    errors.append(f"{table_name}: emitted CSV row count does not match the detected change count")
                if errors:
                    run.record_validation_errors(errors)
                    raise ContractValidationError(errors)

            deletions_path = stage / "deletions.csv"
            _write_deletions(deletions_path, deletion_rows)
            with deletions_path.open(encoding="utf-8", newline="") as source:
                reader = csv.reader(source, strict=True)
                if tuple(next(reader, ())) != DELETIONS_HEADER:
                    raise ContractValidationError(["deletions: header does not match the documented tombstone contract"])
                for row_number, row in enumerate(reader, start=2):
                    if len(row) != 2 or row[0] not in CONTRACTS or not row[1]:
                        error = f"deletions: row {row_number} has an invalid table/key field"
                        run.record_validation_errors([error])
                        raise ContractValidationError([error])

            acceptance_status = decide_acceptance(
                validation_passed=True,
                warnings=validation_warnings,
            )
            run.record_acceptance_status(acceptance_status)
            manifest = {
                "pipeline_run_id": run.run_id,
                "extraction_window": run.extraction_window,
                "previous_successful_run_id": previous_run_id,
                "baseline": previous_run_id is None,
                "validation_result": "PASS",
                "full_snapshot_relationship_validation": "PASS",
                "acceptance_status": acceptance_status,
                "validation_warnings": validation_warnings,
                "log_ref": str(run.log_path),
                "source_row_counts": source_counts,
                "extracted_row_counts": {
                    table: len(changed_rows[table]) for table in CONTRACTS
                },
                "deleted_key_counts": {
                    table: sum(1 for deleted_table, _ in deletion_rows if deleted_table == table)
                    for table in CONTRACTS
                },
                "source_change_detection": "SHA-256 over stable primary key and canonical row values",
                "watermark_advanced_after": "atomic CSV batch publication and database state commit",
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            manifest_path = stage / "extraction_metadata.json"
            with manifest_path.open("x", encoding="utf-8") as output:
                json.dump(manifest, output, ensure_ascii=False, sort_keys=True)
                output.write("\n")
            os.chmod(manifest_path, 0o600)
            os.chmod(stage, 0o700)
            record_acceptance(
                stage,
                run_id=run.run_id,
                validation_passed=True,
                warnings=validation_warnings,
                log_ref=str(run.log_path),
                write_marker=False,
            )
            _fsync_tree_files(stage)

            if destination.exists() or destination.is_symlink():
                raise PipelineError("Output directory appeared during the run; refusing publication")
            os.rename(stage, destination)
            published = True
            _fsync_directory(destination.parent)

        assert run is not None
        completed_at = datetime.now(timezone.utc)
        if acceptance_status == APPROVED:
            with control.transaction():
                control.execute(f"DELETE FROM {STATE_TABLE}")
                state_rows = [
                    (table, key, digest)
                    for table in CONTRACTS
                    for key, digest in current_state[table].items()
                ]
                if state_rows:
                    with control.cursor() as cursor:
                        cursor.executemany(
                            f"INSERT INTO {STATE_TABLE} (table_name, record_key, content_sha256) VALUES (%s, %s, %s)",
                            state_rows,
                        )
                control.execute(
                    f"""INSERT INTO {WATERMARK_TABLE}
                        (singleton, last_successful_run_id, last_successful_at)
                        VALUES (TRUE, %s, %s)
                        ON CONFLICT (singleton) DO UPDATE SET
                            last_successful_run_id = EXCLUDED.last_successful_run_id,
                            last_successful_at = EXCLUDED.last_successful_at""",
                    (run.run_id, completed_at),
                )
        else:
            with control.transaction():
                control.execute(
                    f"INSERT INTO {PENDING_RUN_TABLE} (run_id, previous_run_id, completed_at) VALUES (%s, %s, %s)",
                    (run.run_id, previous_run_id, completed_at),
                )
                state_rows = [
                    (run.run_id, table, key, digest)
                    for table in CONTRACTS
                    for key, digest in current_state[table].items()
                ]
                if state_rows:
                    with control.cursor() as cursor:
                        cursor.executemany(
                            f"INSERT INTO {PENDING_STATE_TABLE} (run_id, table_name, record_key, content_sha256) VALUES (%s, %s, %s, %s)",
                            state_rows,
                        )
        state_committed = True
        if published and state_committed and acceptance_status == APPROVED:
            write_handover_marker(destination, run.run_id)
        return {
            "pipeline_run_id": run.run_id,
            "baseline": previous_run_id is None,
            "acceptance_status": acceptance_status,
            "validation_warnings": validation_warnings,
            "source_counts": source_counts,
            "extracted_counts": {table: len(changed_rows[table]) for table in CONTRACTS},
            "deleted_counts": {
                table: sum(1 for deleted_table, _ in deletion_rows if deleted_table == table)
                for table in CONTRACTS
            },
            "output_dir": str(destination),
        }
    except Exception as exc:
        if published and not state_committed:
            shutil.rmtree(destination, ignore_errors=True)
        elif not published:
            shutil.rmtree(stage, ignore_errors=True)
        if isinstance(exc, (DatabaseConfigurationError, DatabaseConnectionError,
                            IncrementalPipelineError, PipelineError, RunMetadataError,
                            ContractValidationError, OSError, ValueError)):
            raise
        raise IncrementalPipelineError(safe_error_summary(exc)) from exc
    finally:
        if control is not None:
            try:
                control.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))
            except Exception:
                pass
            control.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export only changed rows from a content-hash snapshot of the five source tables."
    )
    parser.add_argument("--output-dir", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_incremental_pipeline(args.output_dir)
    except Exception as exc:
        print(f"Incremental pipeline failed: {safe_error_summary(exc)}", file=sys.stderr)
        return 1
    print(
        "Published incremental batch "
        f"{result['pipeline_run_id']} baseline={result['baseline']} "
        f"acceptance={result['acceptance_status']} "
        f"source_counts={result['source_counts']} "
        f"extracted_counts={result['extracted_counts']} "
        f"deleted_counts={result['deleted_counts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
