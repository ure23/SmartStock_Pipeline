from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smartstock_pipeline.scheduled_runner import (
    _load_database_environment,
    run_scheduled_batch,
)


class ScheduledRunnerTests(unittest.TestCase):
    def _write_env(self, path: Path) -> None:
        path.write_text(
            "SMARTSTOCK_DB_HOST=127.0.0.1\n"
            "SMARTSTOCK_DB_PORT=15432\n"
            "SMARTSTOCK_DB_NAME=synthetic\n"
            "SMARTSTOCK_DB_USER=worker\n"
            "SMARTSTOCK_DB_PASSWORD='sensitive=value'\n"
            "SMARTSTOCK_DB_CONNECT_TIMEOUT=5\n"
            "POSTGRES_ADMIN_PASSWORD=must-not-load\n",
            encoding="utf-8",
        )
        os.chmod(path, 0o600)

    def test_env_loader_accepts_owner_only_file_and_ignores_admin_secret(self) -> None:
        with tempfile.TemporaryDirectory(dir="/root/tmp") as temp:
            env_file = Path(temp) / ".env"
            self._write_env(env_file)
            previous = {key: os.environ.get(key) for key in (
                "SMARTSTOCK_DB_HOST", "SMARTSTOCK_DB_PORT", "SMARTSTOCK_DB_NAME",
                "SMARTSTOCK_DB_USER", "SMARTSTOCK_DB_PASSWORD",
                "SMARTSTOCK_DB_CONNECT_TIMEOUT", "POSTGRES_ADMIN_PASSWORD",
            )}
            try:
                os.environ.pop("POSTGRES_ADMIN_PASSWORD", None)
                _load_database_environment(env_file)
                self.assertEqual(os.environ["SMARTSTOCK_DB_PASSWORD"], "sensitive=value")
                self.assertNotIn("POSTGRES_ADMIN_PASSWORD", os.environ)
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_env_loader_rejects_group_or_world_readable_file(self) -> None:
        with tempfile.TemporaryDirectory(dir="/root/tmp") as temp:
            env_file = Path(temp) / ".env"
            self._write_env(env_file)
            os.chmod(env_file, 0o644)
            with self.assertRaisesRegex(RuntimeError, "owner-only"):
                _load_database_environment(env_file)

    def test_scheduled_run_uses_private_batch_directory_and_incremental_runner(self) -> None:
        with tempfile.TemporaryDirectory(dir="/root/tmp") as temp:
            root = Path(temp) / "private" / "handover"
            env_file = Path(temp) / ".env"
            self._write_env(env_file)
            expected = {"pipeline_run_id": "synthetic-run", "output_dir": "synthetic"}
            with patch("smartstock_pipeline.scheduled_runner.run_incremental_pipeline", return_value=expected) as run:
                result = run_scheduled_batch(output_root=root, env_file=env_file)
            self.assertEqual(result, expected)
            target = Path(run.call_args.args[0])
            self.assertEqual(target.parent, root)
            self.assertRegex(target.name, r"^batch-\d{8}T\d{6}\+0800$")
            self.assertEqual(stat.S_IMODE(root.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((root.parent / "scheduled-run.lock").stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
