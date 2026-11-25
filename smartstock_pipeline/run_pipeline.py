"""Run the five full-snapshot extractors as one validated handover batch."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from smartstock_pipeline.acceptance import (
    decide_acceptance,
    record_acceptance,
    write_handover_marker,
)
from smartstock_pipeline.db import (
    DatabaseConfig,
    DatabaseConfigurationError,
    DatabaseConnectionError,
    connect,
)
from smartstock_pipeline.extract_inventory import extract_inventory
from smartstock_pipeline.extract_orders import extract_orders_and_items
from smartstock_pipeline.extract_products_materials import extract_products_materials
from smartstock_pipeline.extract_stock_movements import extract_stock_movements
from smartstock_pipeline.run_metadata import ExtractionRun, RunMetadataError, safe_error_summary
from smartstock_pipeline.validate_contract import (
    CONTRACTS,
    ContractValidationError,
    validate_outputs,
)

OUTPUT_NAMES = {
    "products_materials": "products_materials.csv",
    "inventory": "inventory.csv",
    "orders": "orders.csv",
    "order_items": "order_items.csv",
    "stock_movements": "stock_movements.csv",
}


class PipelineError(RuntimeError):
    """Raised when the full extraction batch cannot be safely published."""


def run_pipeline(
    output_dir: str | Path,
    config: DatabaseConfig | None = None,
) -> dict[str, int]:
    """Export, validate, and atomically publish a complete five-CSV snapshot.

    The destination must not already exist. All work is written to a private
    temporary sibling directory; it becomes visible at ``output_dir`` only
    after every exporter and database-backed contract check succeeds.
    """
    requested = Path(output_dir).expanduser().absolute()
    parent = requested.parent
    parent.mkdir(parents=True, exist_ok=True)
    if not parent.is_dir():
        raise PipelineError("Output parent must be a directory")
    destination = parent.resolve() / requested.name
    if destination.exists() or destination.is_symlink():
        raise PipelineError("Output directory already exists; refusing to overwrite it")

    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.stage-", dir=parent))
    published = False
    output_paths = {
        table: stage / OUTPUT_NAMES[table]
        for table in CONTRACTS
    }
    run = ExtractionRun(tuple(CONTRACTS))
    validated_counts: dict[str, int] = {}
    validation_warnings: list[str] = []
    acceptance_status = "REJECTED"
    try:
        with run:
            counts: dict[str, int] = {}
            counts["products_materials"] = extract_products_materials(
                output_paths["products_materials"], config
            )
            counts["inventory"] = extract_inventory(output_paths["inventory"])
            counts["orders"], counts["order_items"] = extract_orders_and_items(
                output_paths["orders"], output_paths["order_items"], config
            )
            counts["stock_movements"] = extract_stock_movements(
                output_paths["stock_movements"]
            )
            for table_name, count in counts.items():
                run.record_counts(
                    table_name,
                    records_read=count,
                    records_extracted=count,
                )

            try:
                with connect(config) as connection:
                    validated_counts = validate_outputs(
                        output_paths,
                        connection,
                        warning_sink=validation_warnings,
                    )
            except ContractValidationError as exc:
                run.record_validation_errors(exc.errors)
                run.record_validation_warnings(validation_warnings)
                raise

            if validated_counts != counts:
                # validate_outputs already reconciles CSV counts with source
                # counts; this additionally guards exporter return values.
                errors = [
                    f"{table}: exporter count does not match validated CSV count"
                    for table in CONTRACTS
                    if counts[table] != validated_counts[table]
                ]
                run.record_validation_errors(errors)
                run.record_validation_warnings(validation_warnings)
                raise ContractValidationError(errors, validated_counts)

            run.record_validation_warnings(validation_warnings)
            acceptance_status = decide_acceptance(
                validation_passed=True,
                warnings=validation_warnings,
            )
            run.record_acceptance_status(acceptance_status)
            for path in output_paths.values():
                os.chmod(path, 0o600)

            manifest = {
                "pipeline_run_id": run.run_id,
                "extraction_window": "full_snapshot",
                "validation_result": "PASS",
                "acceptance_status": acceptance_status,
                "validation_warnings": validation_warnings,
                "source_row_counts": counts,
                "extracted_row_counts": validated_counts,
                "log_ref": str(run.log_path),
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
            if destination.exists() or destination.is_symlink():
                raise PipelineError("Output directory appeared during the run; refusing publication")
            os.rename(stage, destination)
            published = True

        if acceptance_status == "APPROVED":
            write_handover_marker(destination, run.run_id)
        return validated_counts
    except Exception as exc:
        if published:
            # The destination was absent at start and created only by this run.
            shutil.rmtree(destination, ignore_errors=True)
        else:
            shutil.rmtree(stage, ignore_errors=True)
        if isinstance(exc, (DatabaseConfigurationError, DatabaseConnectionError,
                            PipelineError, RunMetadataError, ContractValidationError,
                            OSError, ValueError)):
            raise
        raise PipelineError(safe_error_summary(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run and validate one full-snapshot Stage 1 extraction batch."
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="New destination directory for the five CSVs; existing directories are never overwritten.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        counts = run_pipeline(args.output_dir)
    except Exception as exc:
        print(f"Pipeline failed: {safe_error_summary(exc)}", file=sys.stderr)
        return 1
    rendered = ", ".join(f"{table}={counts[table]}" for table in CONTRACTS)
    print(f"Validated full-snapshot batch at {Path(args.output_dir).expanduser()} ({rendered})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
