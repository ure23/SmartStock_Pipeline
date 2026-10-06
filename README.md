# SmartStock Pipeline — Stage 1 Extraction

This repository currently documents the Stage 1 extraction requirements. The PostgreSQL connection helper is implemented in `smartstock_pipeline/db.py`.

## PostgreSQL connection setup

Install the Python dependency in a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and provide the database host, database name, login, and password through environment variables. Never commit `.env`; it is ignored by Git. The helper reads `SMARTSTOCK_DB_HOST`, `SMARTSTOCK_DB_PORT`, `SMARTSTOCK_DB_NAME`, `SMARTSTOCK_DB_USER`, `SMARTSTOCK_DB_PASSWORD`, and optional `SMARTSTOCK_DB_CONNECT_TIMEOUT`. It does not load `.env` files itself; inject the settings through the shell, scheduler, or container environment. For a local shell, use `set -a; . ./.env; set +a` before running the helper.

The `database` hostname in the local `.env` is the PostgreSQL service alias on the existing SmartStock candidate Docker network. A process running outside that network must set `SMARTSTOCK_DB_HOST` to a reachable PostgreSQL hostname/address instead. Do not publish or recreate the database container just for this connection.

To check connectivity from a process with the variables loaded:

```sh
python -c 'from smartstock_pipeline.db import check_connection; print(check_connection())'
```

The probe issues only `SELECT 1`. Configuration errors identify missing variable names; connection errors do not include driver diagnostics or credentials.

The development database `smartstock_pipeline` is a separate source database on the existing SmartStock candidate PostgreSQL server. Its dedicated login is stored in the ignored, mode-restricted local `.env`. The existing `smartstock` database and its data were not modified. The five documented source tables are defined in `db/schema.sql` and have been applied; all tables are currently empty because no source records were provided. Apply the schema to a new empty database with `psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/schema.sql` after setting a suitable `DATABASE_URL` through the environment.

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

Run the unit tests with:

```sh
python -m unittest discover -s tests -v
```
