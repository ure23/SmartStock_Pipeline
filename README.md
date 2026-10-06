# SmartStock Pipeline — Stage 1 Extraction

This repository currently documents the Stage 1 extraction requirements. The PostgreSQL connection helper is implemented in `smartstock_pipeline/db.py`.

## PostgreSQL connection setup

Install the Python dependency in a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set the application connection values plus a separate random `POSTGRES_ADMIN_PASSWORD` for Compose. Never commit `.env`; it is ignored by Git. The helper reads `SMARTSTOCK_DB_HOST`, `SMARTSTOCK_DB_PORT`, `SMARTSTOCK_DB_NAME`, `SMARTSTOCK_DB_USER`, `SMARTSTOCK_DB_PASSWORD`, and optional `SMARTSTOCK_DB_CONNECT_TIMEOUT`. It does not load `.env` files itself; inject only the `SMARTSTOCK_DB_*` settings into the pipeline worker environment. Keep `POSTGRES_ADMIN_PASSWORD` confined to the local Compose invocation and do not export it to pipeline workers.

SmartStock Pipeline runs PostgreSQL as its own Compose project and persistent volume, separate from SmartStock Capstone. The database is published only on host loopback at `127.0.0.1:${SMARTSTOCK_DB_PORT}` (default `15432`). Start/manage only the Pipeline database with `docker compose -p smartstock-pipeline --env-file .env -f docker-compose.database.yml ...`; do not attach it to the Capstone Compose project or volume. Keep both the application and PostgreSQL administrator credentials in the ignored, mode-restricted `.env` file.

To check connectivity from a process with the variables loaded:

```sh
python -c 'from smartstock_pipeline.db import check_connection; print(check_connection())'
```

The probe issues only `SELECT 1`. Configuration errors identify missing variable names; connection errors do not include driver diagnostics or credentials.

The development database `smartstock_pipeline` belongs to the dedicated SmartStock Pipeline PostgreSQL service and volume. It is not hosted by the SmartStock Capstone PostgreSQL container or volume. The application login is separate from the PostgreSQL administrator login. The five canonical extraction tables are defined in `db/schema.sql`; raw workbook data that does not map losslessly to that contract is kept in the separate `workbook_import` staging schema. Do not move staged records into canonical tables without an approved mapping. Apply the canonical schema with `psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/schema.sql` after setting a suitable `DATABASE_URL` through the environment.

## Product/material extraction

Run the first-stage product/material extraction after loading the database environment variables:

```sh
python -m smartstock_pipeline.extract_products_materials --output /path/to/products_materials.csv
```

The command exports only `product_id`, `product_name`, `category`, `unit_price`, `reorder_level`, `status`, and `updated_at`, in that order, sorted by `product_id`. It verifies the required source columns, preserves source values without transformations, and writes the completed UTF-8 CSV atomically. A table with no rows produces a CSV containing the documented header and zero data rows; it does not invent sample records.

## Inventory extraction

Run the inventory extraction after loading the database environment variables:

```sh
python -m smartstock_pipeline.extract_inventory --output /path/to/inventory.csv
```

The command exports only `inventory_id`, `product_id`, `quantity_on_hand`, `reorder_level`, and `last_updated`, in that order, sorted by `inventory_id`. It verifies the required source columns, preserves source values without transformations, and writes the completed UTF-8 CSV atomically. An empty source table produces a header-only CSV; it does not invent sample records.

## Orders and order items extraction

Export both related tables to separate CSV files from one read-only, repeatable-read snapshot:

```sh
python -m smartstock_pipeline.extract_orders \
  --orders-output /path/to/orders.csv \
  --order-items-output /path/to/order_items.csv
```

`orders.csv` contains `order_id`, `customer_id`, `order_date`, `status`, and `total_amount`; `order_items.csv` contains `order_item_id`, `order_id`, `product_id`, `quantity`, and `unit_price`. Both datasets are sorted by their primary keys. Required columns and unique primary keys are checked, source values are preserved without transformation, and each UTF-8 CSV is atomically replaced after successful serialization. The `order_id` field is present in both files for relationship tracking. Empty source tables produce header-only CSV files; no sample records are invented.

## Approved workbook mapping and export

The user-approved workbook adapter maps the staged price list and order trackers into canonical products, orders, and order items. Run the mappers in order after loading the database environment variables:

```sh
python -m smartstock_pipeline.import_workbook_products
python -m smartstock_pipeline.import_workbook_orders
```

Generated IDs are persisted in `workbook_import` mapping tables. The order mapper widens `orders.total_amount` and `order_items.quantity` to unconstrained `NUMERIC` to preserve the source precision, and records unmatched order-item source locators/reason codes in `workbook_import.pipeline_quarantine`. Do not delete quarantined source rows or invent replacements. This workbook has no inventory snapshot or stock-movement source; those canonical tables remain empty rather than being synthesized.

For authorized CSV handover, set a restrictive umask and write files to a mode-0700 directory outside this repository. The exporters include only their canonical contract fields; do not commit client-derived CSVs or include row values in logs or AFFiNE. The workbook's `source_file_sha256` is a source-version fingerprint, not a row-modified timestamp, so the adapter does not claim daily incremental completeness.

Run the unit tests with:

```sh
python -m unittest discover -s tests -v
```
