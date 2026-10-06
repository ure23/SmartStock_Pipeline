"""Environment-driven PostgreSQL connection for the extraction pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg
from psycopg import Connection


class DatabaseConfigurationError(ValueError):
    """Raised when required database settings are missing or invalid."""


class DatabaseConnectionError(RuntimeError):
    """Raised when PostgreSQL cannot be reached or rejects the connection."""


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str
    connect_timeout: int = 5

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        required = (
            "SMARTSTOCK_DB_HOST",
            "SMARTSTOCK_DB_NAME",
            "SMARTSTOCK_DB_USER",
            "SMARTSTOCK_DB_PASSWORD",
        )
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise DatabaseConfigurationError(
                "Missing required database environment variable(s): "
                + ", ".join(missing)
            )

        try:
            port = int(os.getenv("SMARTSTOCK_DB_PORT", "5432"))
            timeout = int(os.getenv("SMARTSTOCK_DB_CONNECT_TIMEOUT", "5"))
        except ValueError as exc:
            raise DatabaseConfigurationError(
                "SMARTSTOCK_DB_PORT and SMARTSTOCK_DB_CONNECT_TIMEOUT must be integers"
            ) from exc

        if not 1 <= port <= 65535:
            raise DatabaseConfigurationError("SMARTSTOCK_DB_PORT must be between 1 and 65535")
        if timeout < 1:
            raise DatabaseConfigurationError("SMARTSTOCK_DB_CONNECT_TIMEOUT must be at least 1")

        return cls(
            host=os.environ["SMARTSTOCK_DB_HOST"],
            port=port,
            dbname=os.environ["SMARTSTOCK_DB_NAME"],
            user=os.environ["SMARTSTOCK_DB_USER"],
            password=os.environ["SMARTSTOCK_DB_PASSWORD"],
            connect_timeout=timeout,
        )


def connect(config: DatabaseConfig | None = None) -> Connection:
    """Open a PostgreSQL connection using explicit config or environment settings."""
    settings = config or DatabaseConfig.from_env()
    try:
        return psycopg.connect(
            host=settings.host,
            port=settings.port,
            dbname=settings.dbname,
            user=settings.user,
            password=settings.password,
            connect_timeout=settings.connect_timeout,
        )
    except psycopg.Error as exc:
        # Do not include connection parameters or exception text: providers may
        # include sensitive connection details in their diagnostic message.
        raise DatabaseConnectionError(
            f"Could not connect to PostgreSQL at {settings.host}:{settings.port}/"
            f"{settings.dbname} as {settings.user}"
        ) from exc


def check_connection(config: DatabaseConfig | None = None) -> bool:
    """Verify connectivity with a read-only SELECT 1 probe."""
    with connect(config) as connection:
        row = connection.execute("SELECT 1").fetchone()
    if row != (1,):
        raise DatabaseConnectionError("PostgreSQL connection probe returned an unexpected result")
    return True
