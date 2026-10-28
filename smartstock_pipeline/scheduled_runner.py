"""Secure daily entrypoint for the incremental Stage 1 pipeline."""

from __future__ import annotations

import argparse
import fcntl
import os
import shlex
import stat
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from smartstock_pipeline.db import DatabaseConfigurationError, DatabaseConfig
from smartstock_pipeline.incremental_pipeline import run_incremental_pipeline
from smartstock_pipeline.run_metadata import safe_error_summary

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = REPOSITORY_ROOT / ".env"
DEFAULT_DATA_ROOT = Path.home() / ".local" / "share" / "smartstock-pipeline"
DEFAULT_EXPORT_ROOT = DEFAULT_DATA_ROOT / "handover"
DATABASE_KEYS = {
    "SMARTSTOCK_DB_HOST",
    "SMARTSTOCK_DB_PORT",
    "SMARTSTOCK_DB_NAME",
    "SMARTSTOCK_DB_USER",
    "SMARTSTOCK_DB_PASSWORD",
    "SMARTSTOCK_DB_CONNECT_TIMEOUT",
}


class ScheduledRunnerError(RuntimeError):
    """Raised for unsafe scheduled-run configuration or storage."""


def _load_database_environment(env_file: str | Path) -> None:
    path = Path(env_file).expanduser()
    try:
        info = path.lstat()
    except OSError as exc:
        raise ScheduledRunnerError("Database environment file is unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ScheduledRunnerError("Database environment file must be a regular file")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ScheduledRunnerError("Database environment file must be owner-only")

    loaded: dict[str, str] = {}
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            key = key.strip()
            if key not in DATABASE_KEYS:
                continue
            pieces = shlex.split(raw_value.strip(), comments=False, posix=True)
            if len(pieces) != 1 or not pieces[0]:
                raise ScheduledRunnerError("Database environment file has an invalid value format")
            loaded[key] = pieces[0]
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, ScheduledRunnerError):
            raise
        raise ScheduledRunnerError("Database environment file could not be parsed safely") from exc

    required = DATABASE_KEYS - {"SMARTSTOCK_DB_PORT", "SMARTSTOCK_DB_CONNECT_TIMEOUT"}
    missing = sorted(required - loaded.keys())
    if missing:
        raise DatabaseConfigurationError(
            "Missing required database environment variable(s): " + ", ".join(missing)
        )
    os.environ.update(loaded)
    DatabaseConfig.from_env()


def _ensure_private_directory(path: Path) -> None:
    path = path.expanduser()
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = path.lstat()
    except OSError as exc:
        raise ScheduledRunnerError("Private pipeline output directory is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ScheduledRunnerError("Pipeline output location must be a real directory")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ScheduledRunnerError("Pipeline output directory must be owner-only (0700)")


def run_scheduled_batch(
    *,
    output_root: str | Path = DEFAULT_EXPORT_ROOT,
    env_file: str | Path = DEFAULT_ENV_FILE,
) -> dict[str, object] | None:
    """Run one incremental batch; skip cleanly if another run holds the lock."""
    root = Path(output_root).expanduser().absolute()
    data_root = root.parent
    _ensure_private_directory(data_root)
    _ensure_private_directory(root)
    log_dir = data_root / "logs"
    _ensure_private_directory(log_dir)
    os.environ["SMARTSTOCK_LOG_DIR"] = str(log_dir)
    _load_database_environment(env_file)

    lock_path = data_root / "scheduled-run.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ScheduledRunnerError("Scheduled-run lock file is not safe")
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return None

        run_time = datetime.now(ZoneInfo("Asia/Manila"))
        batch_dir = root / f"batch-{run_time.strftime('%Y%m%dT%H%M%S%z')}"
        return run_incremental_pipeline(batch_dir)
    finally:
        os.close(descriptor)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one content-hash incremental batch for the daily Stage 1 schedule."
    )
    parser.add_argument("--output-root", default=str(DEFAULT_EXPORT_ROOT))
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_scheduled_batch(output_root=args.output_root, env_file=args.env_file)
    except Exception as exc:
        print(f"Scheduled extraction failed: {safe_error_summary(exc)}", file=sys.stderr)
        return 1
    if result is None:
        print("Skipped: another incremental extraction is already running.")
        return 0
    print(
        f"Scheduled batch {result['pipeline_run_id']} published to {result['output_dir']}; "
        f"baseline={result['baseline']} acceptance={result['acceptance_status']} "
        f"extracted_counts={result['extracted_counts']} "
        f"deleted_counts={result['deleted_counts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
