from __future__ import annotations

"""Run an isolated PostgreSQL end-to-end test of the Stage 1 incremental pipeline.

This creates and drops only a uniquely named disposable database on the configured
SmartStock Pipeline PostgreSQL server. All inserted records are synthetic.
"""

import csv
import json
import os
import shlex
import stat
import sys
import tempfile
import uuid
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg
from psycopg import sql

from smartstock_pipeline.db import DatabaseConfig, connect
from smartstock_pipeline.incremental_pipeline import run_incremental_pipeline
from smartstock_pipeline.validate_contract import CONTRACTS

DATABASE_PREFIX = "smartstock_pipeline_test_"
ENV_FILE = ROOT / ".env"


def _load_settings(path: Path) -> tuple[DatabaseConfig, str]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RuntimeError("Environment file must be a regular file")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError("Environment file must be owner-only")

    allowed = {
        "SMARTSTOCK_DB_HOST",
        "SMARTSTOCK_DB_PORT",
        "SMARTSTOCK_DB_NAME",
        "SMARTSTOCK_DB_USER",
        "SMARTSTOCK_DB_PASSWORD",
        "SMARTSTOCK_DB_CONNECT_TIMEOUT",
        "POSTGRES_ADMIN_PASSWORD",
    }
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key not in allowed:
            continue
        parsed = shlex.split(raw_value.strip(), comments=False, posix=True)
        if len(parsed) != 1 or not parsed[0]:
            raise RuntimeError("Environment file has an invalid value format")
        values[key] = parsed[0]

    required = {
        "SMARTSTOCK_DB_HOST",
        "SMARTSTOCK_DB_NAME",
        "SMARTSTOCK_DB_USER",
        "SMARTSTOCK_DB_PASSWORD",
        "POSTGRES_ADMIN_PASSWORD",
    }
    missing = required - values.keys()
    if missing:
        raise RuntimeError("Environment file is missing required connection settings")

    app_config = DatabaseConfig(
        host=values["SMARTSTOCK_DB_HOST"],
        port=int(values.get("SMARTSTOCK_DB_PORT", "5432")),
        dbname=values["SMARTSTOCK_DB_NAME"],
        user=values["SMARTSTOCK_DB_USER"],
        password=values["SMARTSTOCK_DB_PASSWORD"],
        connect_timeout=int(values.get("SMARTSTOCK_DB_CONNECT_TIMEOUT", "5")),
    )
    if (app_config.host not in {"127.0.0.1", "localhost", "::1"}
            or app_config.port != 15432
            or app_config.dbname != "smartstock_pipeline"):
        raise RuntimeError("Integration tests require the dedicated loopback Pipeline development database")
    if app_config.dbname.startswith(DATABASE_PREFIX):
        raise RuntimeError("Refusing to use an existing test database as the source target")
    return app_config, values["POSTGRES_ADMIN_PASSWORD"]


def _counts(result: dict[str, object], field: str) -> dict[str, int]:
    values = result[field]
    if not isinstance(values, dict):
        raise AssertionError(f"{field} is not a count mapping")
    return cast(dict[str, int], values)


def _assert_batch(directory: Path, *, baseline: bool) -> dict[str, int]:
    manifest = json.loads((directory / "extraction_metadata.json").read_text(encoding="utf-8"))
    marker = json.loads((directory / "handover_ready.json").read_text(encoding="utf-8"))
    assert manifest["validation_result"] == "PASS"
    assert marker["handover_status"] == "VALIDATED"
    assert marker["pipeline_run_id"] == manifest["pipeline_run_id"]
    assert manifest["baseline"] is baseline
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700

    counts: dict[str, int] = {}
    required_files = {"deletions.csv", "extraction_metadata.json", "handover_ready.json"}
    for table, contract in CONTRACTS.items():
        path = directory / f"{table}.csv"
        required_files.add(path.name)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.reader(source, strict=True)
            assert tuple(next(reader, ())) == contract.headers
            counts[table] = sum(1 for _ in reader)
    assert {item.name for item in directory.iterdir()} == required_files
    assert all(stat.S_IMODE(item.stat().st_mode) == 0o600 for item in directory.iterdir())
    return counts


def main() -> None:
    app_base, admin_password = _load_settings(ENV_FILE)
    database_name = DATABASE_PREFIX + uuid.uuid4().hex[:12]
    app_config = DatabaseConfig(
        app_base.host,
        app_base.port,
        database_name,
        app_base.user,
        app_base.password,
        app_base.connect_timeout,
    )
    admin_config = {
        "host": app_base.host,
        "port": app_base.port,
        "dbname": "postgres",
        "user": "postgres",
        "password": admin_password,
        "connect_timeout": app_base.connect_timeout,
    }

    temp_context = tempfile.TemporaryDirectory(prefix="smartstock-stage1-e2e-", dir="/root/tmp")
    output_root = Path(temp_context.name)
    os.chmod(output_root, 0o700)
    log_dir = output_root / "logs"
    os.environ["SMARTSTOCK_LOG_DIR"] = str(log_dir)
    database_created = False
    try:
        with psycopg.connect(**admin_config, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
            database_created = True
            admin.execute(
                sql.SQL("GRANT CONNECT, CREATE ON DATABASE {} TO {}").format(
                    sql.Identifier(database_name), sql.Identifier(app_base.user)
                )
            )
        with psycopg.connect(**{**admin_config, "dbname": database_name}, autocommit=True) as admin:
            admin.execute(
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
                    sql.Identifier(app_base.user)
                )
            )
        with connect(app_config) as database:
            database.execute((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))

        with connect(app_config) as database:
            database.execute(
                "INSERT INTO products_materials VALUES (1,'Synthetic item','Test',10.00,1,'ACTIVE',NULL)"
            )
            database.execute("INSERT INTO inventory VALUES (1,1,5,1,NULL)")
            database.execute("INSERT INTO orders VALUES (1,2,'2026-10-01','OPEN',10.00)")
            database.execute("INSERT INTO order_items VALUES (1,1,1,1,10.00)")
            database.execute(
                "INSERT INTO stock_movements VALUES (1,1,'IN',5,'2026-10-01 09:00:00',NULL)"
            )

        baseline = run_incremental_pipeline(output_root / "batch-baseline", app_config)
        baseline_counts = _assert_batch(output_root / "batch-baseline", baseline=True)
        assert baseline_counts == {table: 1 for table in CONTRACTS}
        assert _counts(baseline, "extracted_counts") == baseline_counts

        unchanged = run_incremental_pipeline(output_root / "batch-unchanged", app_config)
        unchanged_counts = _assert_batch(output_root / "batch-unchanged", baseline=False)
        assert all(count == 0 for count in unchanged_counts.values())
        assert all(count == 0 for count in _counts(unchanged, "deleted_counts").values())

        with connect(app_config) as database:
            database.execute("UPDATE products_materials SET unit_price=11.00 WHERE product_id=1")
            database.execute("UPDATE inventory SET quantity_on_hand=4 WHERE inventory_id=1")
            database.execute("UPDATE orders SET status='CLOSED' WHERE order_id=1")
            database.execute("DELETE FROM order_items WHERE order_item_id=1")
            database.execute(
                "INSERT INTO stock_movements VALUES (2,1,'OUT',1,'2026-10-02 09:00:00',NULL)"
            )

        changed = run_incremental_pipeline(output_root / "batch-changed", app_config)
        changed_counts = _assert_batch(output_root / "batch-changed", baseline=False)
        assert changed_counts == {
            "products_materials": 1,
            "inventory": 1,
            "orders": 1,
            "order_items": 0,
            "stock_movements": 1,
        }
        assert _counts(changed, "deleted_counts")["order_items"] == 1
        with (output_root / "batch-changed" / "deletions.csv").open(
            encoding="utf-8", newline=""
        ) as source:
            tombstones = list(csv.DictReader(source))
        assert len(tombstones) == 1 and tombstones[0]["table_name"] == "order_items"

        final_unchanged = run_incremental_pipeline(output_root / "batch-final-unchanged", app_config)
        assert all(count == 0 for count in _counts(final_unchanged, "extracted_counts").values())
        assert all(count == 0 for count in _counts(final_unchanged, "deleted_counts").values())
        recoverable_marker = output_root / "batch-final-unchanged" / "handover_ready.json"
        recoverable_marker.unlink()
        run_incremental_pipeline(output_root / "batch-recovery", app_config)
        assert recoverable_marker.is_file()

        with connect(app_config) as database:
            previous_watermark = database.execute(
                "SELECT last_successful_run_id FROM pipeline_extraction_watermark WHERE singleton=TRUE"
            ).fetchone()[0]
            database.execute("DROP TABLE stock_movements")
        failed = False
        try:
            run_incremental_pipeline(output_root / "batch-failed", app_config)
        except Exception:
            failed = True
        assert failed
        assert not (output_root / "batch-failed").exists()
        with connect(app_config) as database:
            current_watermark = database.execute(
                "SELECT last_successful_run_id FROM pipeline_extraction_watermark WHERE singleton=TRUE"
            ).fetchone()[0]
        assert current_watermark == previous_watermark

        logs = list(log_dir.glob("*.json"))
        assert logs
        log_data = [json.loads(path.read_text(encoding="utf-8")) for path in logs]
        assert any(entry.get("extraction_status") == "SUCCESS" for entry in log_data)
        assert any(entry.get("extraction_status") == "FAILED" for entry in log_data)
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in logs)

        print("stage1_synthetic_postgresql_e2e=PASS")
        print("baseline_rows=5; unchanged_delta_rows=0; changed_tables=4; deletion_tombstones=1")
        print("failed_schema_no_publish_and_watermark_unchanged=PASS")
        print("metadata_success_failure_and_marker_recovery=PASS")
        print("csv_contract_headers_and_private_permissions=PASS")
    finally:
        if database_created:
            try:
                with psycopg.connect(**admin_config, autocommit=True) as admin:
                    admin.execute(
                        sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                            sql.Identifier(database_name)
                        )
                    )
            except Exception as exc:
                raise RuntimeError("Failed to remove disposable synthetic integration database") from exc
        temp_context.cleanup()


if __name__ == "__main__":
    main()
