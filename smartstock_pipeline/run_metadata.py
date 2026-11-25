"""Write privacy-safe metadata for extraction runs and enforce log retention."""

from __future__ import annotations

import json
import os
import stat
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from smartstock_pipeline.db import DatabaseConfigurationError, DatabaseConnectionError

DEFAULT_LOG_DIR = Path("logs")
DEFAULT_RETENTION_DAYS = 30


class RunMetadataError(RuntimeError):
    """Raised when a run record cannot be written safely."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _secure_directory(path: Path, *, create: bool) -> None:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RunMetadataError("Run log location must be a real directory")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RunMetadataError("Run log directory must be owned by the current user and mode 0700")


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, (DatabaseConfigurationError, DatabaseConnectionError)):
        return f"{type(exc).__name__}: {exc}"
    return f"{type(exc).__name__}: details suppressed to protect source data"


def safe_error_summary(exc: BaseException) -> str:
    """Return an error summary safe for console output and persistent logs."""
    return _safe_error(exc)


def _read_log(path: Path) -> dict[str, Any] | None:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            return None
        if stat.S_IMODE(info.st_mode) != 0o600:
            return None
        with path.open(encoding="utf-8") as source:
            value = json.load(source)
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def prune_expired_logs(
    log_dir: str | Path = DEFAULT_LOG_DIR,
    *,
    now: datetime | None = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> int:
    """Delete only expired successful logs; preserve failed or unrecognized logs."""
    if retention_days < DEFAULT_RETENTION_DAYS:
        raise ValueError("Run log retention must be at least 30 days")
    directory = Path(log_dir).expanduser()
    if not directory.exists():
        return 0
    _secure_directory(directory, create=False)
    cutoff = (now or _utc_now()) - timedelta(days=retention_days)
    removed = 0
    for path in directory.glob("*.json"):
        metadata = _read_log(path)
        if metadata is None or metadata.get("extraction_status") != "SUCCESS":
            continue
        ended = metadata.get("end_timestamp")
        if not isinstance(ended, str):
            continue
        try:
            ended_at = datetime.fromisoformat(ended.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ended_at.tzinfo is None or ended_at >= cutoff:
            continue
        info = path.lstat()
        if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid():
            path.unlink()
            removed += 1
    return removed


class ExtractionRun:
    """Context manager that records counts, timestamps, status, and safe errors."""

    def __init__(
        self,
        table_names: tuple[str, ...],
        *,
        log_dir: str | Path | None = None,
        extraction_window: str = "full_snapshot",
    ) -> None:
        if not table_names or any(not name for name in table_names):
            raise ValueError("At least one source table name is required")
        self.run_id = f"RUN-{uuid.uuid4()}"
        self.table_names = table_names
        self.log_dir = Path(log_dir or os.getenv("SMARTSTOCK_LOG_DIR", DEFAULT_LOG_DIR)).expanduser()
        self.extraction_window = extraction_window
        self.started_at: datetime | None = None
        self.ended_at: datetime | None = None
        self._counts = {name: {"records_read": 0, "records_extracted": 0, "records_rejected": 0} for name in table_names}
        self._error_message: str | None = None
        self._validation_errors: list[str] = []
        self._validation_warnings: list[str] = []
        self._acceptance_status: str | None = None
        self.metadata: dict[str, Any] | None = None

    @property
    def log_path(self) -> Path:
        return self.log_dir / f"{self.run_id}.json"

    def __enter__(self) -> "ExtractionRun":
        self.started_at = _utc_now()
        return self

    def record_counts(
        self,
        table_name: str,
        *,
        records_read: int,
        records_extracted: int,
        records_rejected: int = 0,
    ) -> None:
        if table_name not in self._counts:
            raise ValueError(f"Table {table_name} is not part of this extraction run")
        if min(records_read, records_extracted, records_rejected) < 0:
            raise ValueError("Extraction record counts cannot be negative")
        self._counts[table_name] = {
            "records_read": records_read,
            "records_extracted": records_extracted,
            "records_rejected": records_rejected,
        }

    def record_validation_errors(self, errors: Sequence[str]) -> None:
        """Attach value-free contract diagnostics to the run metadata."""
        if any(not isinstance(error, str) for error in errors):
            raise TypeError("Validation errors must be strings")
        self._validation_errors = list(errors)

    def record_validation_warnings(self, warnings: Sequence[str]) -> None:
        """Attach non-critical, value-free diagnostics that require manual review."""
        if any(not isinstance(warning, str) for warning in warnings):
            raise TypeError("Validation warnings must be strings")
        self._validation_warnings = list(warnings)

    def record_acceptance_status(self, status: str) -> None:
        """Record a pipeline acceptance status without changing validation outcome."""
        if status not in {"APPROVED", "MANUAL REVIEW", "REJECTED"}:
            raise ValueError("Unknown extraction acceptance status")
        self._acceptance_status = status

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.ended_at = _utc_now()
        if exc is not None:
            self._error_message = _safe_error(exc)
        elapsed = (self.ended_at - (self.started_at or self.ended_at)).total_seconds()
        records = {
            name: self._counts[name]
            for name in self.table_names
        }
        self.metadata = {
            "pipeline_run_id": self.run_id,
            "table_names": list(self.table_names),
            "extraction_window": self.extraction_window,
            "start_timestamp": _timestamp(self.started_at or self.ended_at),
            "end_timestamp": _timestamp(self.ended_at),
            "extraction_status": "FAILED" if exc is not None else "SUCCESS",
            "records": records,
            "records_read": sum(item["records_read"] for item in records.values()),
            "records_extracted": sum(item["records_extracted"] for item in records.values()),
            "records_rejected": sum(item["records_rejected"] for item in records.values()),
            "validation_result": "FAIL" if exc is not None else "PASS",
            "validation_errors": self._validation_errors,
            "validation_warnings": self._validation_warnings,
            "acceptance_status": (
                "REJECTED" if exc is not None else self._acceptance_status or "NOT_EVALUATED"
            ),
            "log_ref": str(self.log_path),
            "error_message": self._error_message,
            "duration_seconds": round(elapsed, 6),
        }
        try:
            _secure_directory(self.log_dir, create=True)
            prune_expired_logs(self.log_dir)
            self._write_metadata()
        except (OSError, RunMetadataError) as log_error:
            if exc is not None:
                raise RunMetadataError(
                    "Extraction failed and its run log could not be recorded: "
                    f"{log_error}"
                ) from exc
            raise RunMetadataError(
                "Extraction completed but its run log could not be recorded: "
                f"{log_error}"
            ) from log_error
        return False

    def _write_metadata(self) -> None:
        assert self.metadata is not None
        path = self.log_dir / f"{self.run_id}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(self.metadata, output, ensure_ascii=False, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
        except Exception:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            raise
