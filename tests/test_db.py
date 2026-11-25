from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

import psycopg

from smartstock_pipeline.db import (
    DatabaseConfig,
    DatabaseConfigurationError,
    DatabaseConnectionError,
    check_connection,
    connect,
)


class DatabaseConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "SMARTSTOCK_DB_HOST": "localhost",
                "SMARTSTOCK_DB_PORT": "5432",
                "SMARTSTOCK_DB_NAME": "smartstock_pipeline",
                "SMARTSTOCK_DB_USER": "pipeline_user",
                "SMARTSTOCK_DB_PASSWORD": "test-secret",
            },
            clear=True,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_reads_required_environment_and_defaults(self) -> None:
        config = DatabaseConfig.from_env()
        self.assertEqual(config.host, "localhost")
        self.assertEqual(config.port, 5432)
        self.assertEqual(config.dbname, "smartstock_pipeline")
        self.assertEqual(config.user, "pipeline_user")
        self.assertEqual(config.connect_timeout, 5)

    def test_missing_secret_is_named_but_never_echoed(self) -> None:
        os.environ.pop("SMARTSTOCK_DB_PASSWORD")
        with self.assertRaisesRegex(DatabaseConfigurationError, "SMARTSTOCK_DB_PASSWORD"):
            DatabaseConfig.from_env()

    def test_invalid_port_is_rejected(self) -> None:
        os.environ["SMARTSTOCK_DB_PORT"] = "not-a-port"
        with self.assertRaisesRegex(DatabaseConfigurationError, "must be integers"):
            DatabaseConfig.from_env()

    @patch("smartstock_pipeline.db.psycopg.connect")
    def test_connect_passes_settings_without_logging_them(self, mock_connect: MagicMock) -> None:
        config = DatabaseConfig("db.internal", 5432, "smartstock_pipeline", "pipeline_user", "secret")
        connect(config)
        mock_connect.assert_called_once_with(
            host="db.internal",
            port=5432,
            dbname="smartstock_pipeline",
            user="pipeline_user",
            password="secret",
            connect_timeout=5,
        )

    @patch("smartstock_pipeline.db.psycopg.connect", side_effect=psycopg.OperationalError("secret diagnostic"))
    def test_connection_errors_do_not_expose_driver_details(self, _mock_connect: MagicMock) -> None:
        config = DatabaseConfig("db.internal", 5432, "smartstock_pipeline", "pipeline_user", "secret")
        with self.assertRaises(DatabaseConnectionError) as raised:
            connect(config)
        self.assertNotIn("secret diagnostic", str(raised.exception))
        self.assertIn("smartstock_pipeline", str(raised.exception))

    @patch("smartstock_pipeline.db.connect")
    def test_health_probe_runs_select_one(self, mock_connect: MagicMock) -> None:
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.fetchone.return_value = (1,)
        mock_connect.return_value = connection
        self.assertTrue(check_connection())
        connection.execute.assert_called_once_with("SELECT 1")


if __name__ == "__main__":
    unittest.main()
