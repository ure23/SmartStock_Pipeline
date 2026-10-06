"""Export the documented products/materials source table to CSV."""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

import psycopg

from smartstock_pipeline.db import (
    DatabaseConfig,
    DatabaseConfigurationError,
    DatabaseConnectionError,
    connect,
)

TABLE_NAME = "products_materials"
FIELDS = (
    "product_id",
    "product_name",
    "category",
    "unit_price",
    "reorder_level",
    "status",
    "updated_at",
)


class ExtractionError(RuntimeError):
    """Raised when the source table does not satisfy the extraction contract."""


def extract_products_materials(
    output_path: str | Path,
    config: DatabaseConfig | None = None,
) -> int:
    """Export all source rows and return the number of rows written.

    The output is replaced atomically only after the database query and CSV
    serialization succeed. An empty source table produces a header-only CSV.
    """
    output = Path(output_path).expanduser()

    with connect(config) as connection:
        column_rows = connection.execute(
            """SELECT column_name
               FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = %s""",
            (TABLE_NAME,),
        ).fetchall()
        source_columns = {row[0] for row in column_rows}
        missing = [field for field in FIELDS if field not in source_columns]
        if missing:
            raise ExtractionError(
                f"Source table {TABLE_NAME} is missing required column(s): "
                + ", ".join(missing)
            )

        query = "SELECT " + ", ".join(FIELDS) + f" FROM {TABLE_NAME} ORDER BY product_id"
        rows = connection.execute(query).fetchall()

    product_ids = [row[0] for row in rows]
    if len(product_ids) != len(set(product_ids)):
        raise ExtractionError("Source query returned duplicate product_id values")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
            writer = csv.writer(temporary_file, lineterminator="\n")
            writer.writerow(FIELDS)
            writer.writerows(rows)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, output)
    except OSError:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
        raise

    return len(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export products_materials rows to a UTF-8 CSV file."
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Destination path for products_materials.csv",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        row_count = extract_products_materials(args.output)
    except (
        DatabaseConfigurationError,
        DatabaseConnectionError,
        ExtractionError,
        OSError,
        psycopg.Error,
    ) as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 1

    print(f"Exported {row_count} {TABLE_NAME} row(s) to {Path(args.output).expanduser()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
