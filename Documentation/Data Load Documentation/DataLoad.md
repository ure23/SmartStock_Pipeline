# Stage 3: Data Load Documentation

**Project:** SmartStock: An Inventory and Delivery Tracking System with AI-Assisted Analytics for Glassram Glass and Aluminum Supply

**Pipeline Stage:** Stage 3 – Data Load

**Documentation Status:** Proposed Design

## Objective

The objective of this stage is to load the approved transformed SmartStock datasets into a PostgreSQL reporting schema and verify their completeness, accuracy, and traceability. The loaded datasets will support inventory monitoring, sales and transaction analysis, product demand analysis, and stock movement reporting.

This stage uses scheduled batch processing only and does not perform extraction, data cleaning, business transformations, or real-time loading.

## 1. Load Source and Target Specification

### 1.1 Load Input

The Load Stage receives only the approved datasets produced by the Transformation Stage. The transformed CSV files must be accompanied by metadata containing the transformation run ID, batch ID, batch window, record counts, checksums, and validation results.

| Transformed File | Target Table |
| --- | --- |
| dim_product.csv | warehouse.dim_product |
| dim_order.csv | warehouse.dim_order |
| fact_order_item.csv | warehouse.fact_order_item |
| fact_inventory_snapshot.csv | warehouse.fact_inventory_snapshot |
| fact_stock_movement.csv | warehouse.fact_stock_movement |
| agg_monthly_product_demand.csv | warehouse.agg_monthly_product_demand |
| agg_monthly_order_sales.csv | warehouse.agg_monthly_order_sales |
| agg_monthly_product_movement.csv | warehouse.agg_monthly_product_movement |
| agg_annual_stock_in.csv | warehouse.agg_annual_stock_in |

**Proposed Input Location:** `pipeline/handover/transformation/<transformation_run_id>/`

The actual input files must be identified through the approved Transformation Stage output manifest.

| Batch Identifier | Specification / Example |
| --- | --- |
| Transformation Run ID | TRF-20261009-001 |
| Extraction Run ID | RUN-<uuid> |
| Batch ID | BATCH-20261009 |
| Batch Window | Inherited from the Extraction Stage |
| Handover Status | APPROVED |
| Snapshot Type | FULL_CUMULATIVE |

The Transformation Stage must provide a complete cumulative snapshot of all nine datasets, including updated historical aggregates and source deletions. Incremental-only datasets must not be loaded using the full-refresh strategy.

The Load Stage must not re-extract or re-transform data.

### 1.2 Target System

| Item | Specification |
| --- | --- |
| Target System | SmartStock Analytics Warehouse |
| Purpose | Store validated analytical datasets for reporting, dashboards, and business analysis |
| Database Management System | PostgreSQL |
| Target Database | smartstock_pipeline |
| Target Schema | warehouse |
| Audit Schema | pipeline_audit |
| Processing Type | Batch Processing |

The target database is dedicated to the SmartStock Pipeline and is separate from the operational database of the SmartStock application.

### 1.3 Load Method

| Item | Specification |
| --- | --- |
| Load Technology | Python and PostgreSQL SQL |
| Proposed Load Script | smartstock_pipeline/load_pipeline.py |
| Load Frequency | Daily |
| Proposed Load Schedule | 4:00 AM, Philippine Standard Time |
| Load Method | Bulk loading using PostgreSQL COPY and SQL INSERT |
| Write Strategy | Full snapshot refresh |
| Expected Record Count | Based on the approved Transformation Stage metadata |
| Expected Completion Time | Within 30 minutes |

The loading process begins only after the Transformation Stage has been completed and approved.

The transformed datasets are first loaded into temporary staging tables for validation before being written to the target tables. All target changes are performed within a single database transaction.

### 1.4 Load Scope and Order

The tables must be loaded according to their dependencies. Dimension tables are loaded before fact tables and aggregate tables.

| Load Order | Target Table | Dependency |
| --- | --- | --- |
| 1 | dim_product | None |
| 2 | dim_order | None |
| 3 | fact_order_item | dim_product, dim_order |
| 4 | fact_inventory_snapshot | dim_product |
| 5 | fact_stock_movement | dim_product |
| 6 | agg_monthly_product_demand | dim_product |
| 7 | agg_monthly_order_sales | None |
| 8 | agg_monthly_product_movement | dim_product |
| 9 | agg_annual_stock_in | dim_product |

The expected number of records for each batch must match the record counts provided in the approved Transformation Stage handover, including valid zero-row datasets.

### 1.5 Limitations and Assumptions

- Only approved transformed datasets are accepted for loading.
- The Transformation Stage must provide a complete cumulative snapshot of all nine datasets.
- The target database must be available before loading begins.
- The proposed database role, `smartstock_loader`, must have the required SELECT, INSERT, DELETE, temporary table, and audit logging privileges.
- The loader must not have administrative privileges or write access to the operational source database.
- Database credentials must be stored securely using environment variables and must not be included in the repository.
- Loading may be affected by database connection failures, storage limitations, database locks, or large data volumes.
- Loading is scheduled outside normal business hours to minimize operational interruptions.
- Missing transformed files must not be treated as empty datasets.
- Inventory snapshots and stock movements may contain zero records when the source dataset does not provide the necessary information.
- Annual stock-in quantities must not automatically be interpreted as supplier purchases.
- Data types and numerical precision must match the approved Transformation Stage data contract. Incompatible values must be rejected rather than silently converted.

## 2. Target Tables and Column Specification

The target tables are based on the approved output datasets identified in the Transformation Stage. These tables support inventory monitoring, sales analysis, product demand analysis, and stock movement reporting.

### 2.1 Target Table Overview

| Table Name | Table Type | Primary Key | Foreign Keys | Purpose |
| --- | --- | --- | --- | --- |
| dim_product | Dimension | product_id | None | Stores product information and attributes for inventory and sales analysis. |
| dim_order | Dimension | order_id | None | Stores order information, dates, statuses, and reported transaction amounts. |
| fact_order_item | Fact | order_item_id | order_id, product_id | Stores individual order items, quantities, and transaction values. |
| fact_inventory_snapshot | Fact | inventory_id | product_id | Stores the latest available inventory quantities and stock levels. |
| fact_stock_movement | Fact | movement_id | product_id | Stores recorded inward and outward stock movements. |
| agg_monthly_product_demand | Aggregate | order_month, product_id | product_id | Stores monthly product demand and movement classification. |
| agg_monthly_order_sales | Aggregate | order_month | None | Stores monthly sales amounts and order counts. |
| agg_monthly_product_movement | Aggregate | movement_month, product_id | product_id | Stores monthly inward and outward product quantities. |
| agg_annual_stock_in | Aggregate | movement_year, product_id | product_id | Stores annual inward stock quantities. |

### 2.2 Column Specifications

#### dim_product

| Column Name | Data Type | Constraint |
| --- | --- | --- |
| product_id | INTEGER | PRIMARY KEY, NOT NULL |
| product_name | VARCHAR | NOT NULL, nonblank |
| category | VARCHAR | Nullable |
| unit_price | DECIMAL(12,2) | NOT NULL, CHECK >= 0 |
| reorder_level | INTEGER | Nullable, CHECK >= 0 |
| product_status | VARCHAR | Nullable |
| updated_at | TIMESTAMP | Nullable |
| batch_id | TEXT | NOT NULL |
| loaded_at | TIMESTAMPTZ | NOT NULL, DEFAULT CURRENT_TIMESTAMP |

**Reason for Inclusion:** Provides product reference information required by inventory, sales, demand, and stock movement datasets.

#### dim_order

| Column Name | Data Type | Constraint |
| --- | --- | --- |
| order_id | INTEGER | PRIMARY KEY, NOT NULL |
| customer_id | INTEGER | Nullable |
| order_date | DATE | NOT NULL |
| order_status | VARCHAR | NOT NULL |
| reported_total_amount | DECIMAL(12,2) | Nullable, CHECK >= 0 |
| batch_id | TEXT | NOT NULL |
| loaded_at | TIMESTAMPTZ | NOT NULL, DEFAULT CURRENT_TIMESTAMP |

**Reason for Inclusion:** Provides order-level information required for transaction reporting and order-item analysis.

#### fact_order_item

| Column Name | Data Type | Constraint |
| --- | --- | --- |
| order_item_id | INTEGER | PRIMARY KEY, NOT NULL |
| order_id | INTEGER | FOREIGN KEY, NOT NULL |
| product_id | INTEGER | FOREIGN KEY, NOT NULL |
| order_date | DATE | NOT NULL |
| order_status | VARCHAR | NOT NULL |
| quantity | INTEGER | NOT NULL, CHECK > 0 |
| unit_price | DECIMAL(12,2) | NOT NULL, CHECK >= 0 |
| line_amount | DECIMAL(12,2) | NOT NULL, CHECK >= 0 |
| batch_id | TEXT | NOT NULL |
| loaded_at | TIMESTAMPTZ | NOT NULL, DEFAULT CURRENT_TIMESTAMP |

**Foreign Key Relationships:**

- order_id references dim_order(order_id).
- product_id references dim_product(product_id).

**Reason for Inclusion:** Supports item-level sales analysis, product demand monitoring, and transaction reporting.

#### fact_inventory_snapshot

| Column Name | Data Type | Constraint |
| --- | --- | --- |
| inventory_id | INTEGER | PRIMARY KEY, NOT NULL |
| product_id | INTEGER | FOREIGN KEY, NOT NULL |
| quantity_on_hand | INTEGER | NOT NULL, CHECK >= 0 |
| reorder_level | INTEGER | Nullable, CHECK >= 0 |
| last_updated | TIMESTAMP | Nullable |
| stock_level | VARCHAR | Nullable |
| batch_id | TEXT | NOT NULL |
| loaded_at | TIMESTAMPTZ | NOT NULL, DEFAULT CURRENT_TIMESTAMP |

**Foreign Key Relationship:**

- product_id references dim_product(product_id).

**Reason for Inclusion:** Provides the latest available inventory state for monitoring stock availability and stock levels.

#### fact_stock_movement

| Column Name | Data Type | Constraint |
| --- | --- | --- |
| movement_id | INTEGER | PRIMARY KEY, NOT NULL |
| product_id | INTEGER | FOREIGN KEY, NOT NULL |
| movement_date | TIMESTAMP | NOT NULL |
| movement_month | CHAR(7) | NOT NULL, YYYY-MM |
| movement_year | INTEGER | NOT NULL |
| movement_direction | VARCHAR | NOT NULL, IN or OUT |
| quantity | INTEGER | NOT NULL, CHECK > 0 |
| reference_id | INTEGER | Nullable |
| batch_id | TEXT | NOT NULL |
| loaded_at | TIMESTAMPTZ | NOT NULL, DEFAULT CURRENT_TIMESTAMP |

**Foreign Key Relationship:**

- product_id references dim_product(product_id).

**Reason for Inclusion:** Supports the analysis of recorded incoming and outgoing inventory movements.

#### agg_monthly_product_demand

| Column Name | Data Type | Constraint |
| --- | --- | --- |
| order_month | CHAR(7) | NOT NULL, YYYY-MM |
| product_id | INTEGER | FOREIGN KEY, NOT NULL |
| quantity_sold | INTEGER | NOT NULL, CHECK >= 0 |
| movement_class | VARCHAR | Nullable |
| batch_id | TEXT | NOT NULL |
| loaded_at | TIMESTAMPTZ | NOT NULL, DEFAULT CURRENT_TIMESTAMP |

**Composite Primary Key:** order_month, product_id

**Foreign Key Relationship:**

- product_id references dim_product(product_id).

**Reason for Inclusion:** Provides monthly historical product demand and movement classification for downstream business analysis and forecasting.

#### agg_monthly_order_sales

| Column Name | Data Type | Constraint |
| --- | --- | --- |
| order_month | CHAR(7) | PRIMARY KEY, NOT NULL, YYYY-MM |
| order_count | INTEGER | NOT NULL, CHECK >= 0 |
| sales_amount | DECIMAL(12,2) | NOT NULL, CHECK >= 0 |
| batch_id | TEXT | NOT NULL |
| loaded_at | TIMESTAMPTZ | NOT NULL, DEFAULT CURRENT_TIMESTAMP |

**Reason for Inclusion:** Supports the analysis of monthly sales performance and transaction trends.

#### agg_monthly_product_movement

| Column Name | Data Type | Constraint |
| --- | --- | --- |
| movement_month | CHAR(7) | NOT NULL, YYYY-MM |
| product_id | INTEGER | FOREIGN KEY, NOT NULL |
| quantity_in | INTEGER | NOT NULL, CHECK >= 0 |
| quantity_out | INTEGER | NOT NULL, CHECK >= 0 |
| batch_id | TEXT | NOT NULL |
| loaded_at | TIMESTAMPTZ | NOT NULL, DEFAULT CURRENT_TIMESTAMP |

**Composite Primary Key:** movement_month, product_id

**Foreign Key Relationship:**

- product_id references dim_product(product_id).

**Reason for Inclusion:** Supports monthly monitoring of incoming and outgoing product quantities.

#### agg_annual_stock_in

| Column Name | Data Type | Constraint |
| --- | --- | --- |
| movement_year | INTEGER | NOT NULL |
| product_id | INTEGER | FOREIGN KEY, NOT NULL |
| quantity_in | INTEGER | NOT NULL, CHECK >= 0 |
| batch_id | TEXT | NOT NULL |
| loaded_at | TIMESTAMPTZ | NOT NULL, DEFAULT CURRENT_TIMESTAMP |

**Composite Primary Key:** movement_year, product_id

**Foreign Key Relationship:**

- product_id references dim_product(product_id).

**Reason for Inclusion:** Provides an annual summary of recorded inward material quantities for inventory planning.

### 2.3 Indexes and Partitions

PostgreSQL automatically creates unique indexes for primary keys. Additional indexes are proposed for frequently accessed foreign keys and reporting columns.

| Table | Proposed Index |
| --- | --- |
| fact_order_item | order_id, product_id, order_date |
| fact_inventory_snapshot | product_id |
| fact_stock_movement | product_id, movement_date |
| agg_monthly_product_demand | product_id |
| agg_monthly_product_movement | product_id |
| agg_annual_stock_in | product_id |
| All target tables | batch_id |

Table partitioning is not initially required because the actual analytical data volume must first be evaluated.

### 2.4 Match Keys, Batch Identification, and History

The primary keys and composite primary keys serve as the match keys of the target tables.

The batch_id column identifies the batch responsible for loading the current target records, while loaded_at records the loading timestamp.

The dimension tables follow an SCD Type 1-style strategy, where previous attribute values are replaced by the latest approved values.

SCD Type 2 is not implemented. Therefore, effective_from, effective_to, and is_current columns are not required.

The inventory snapshot table represents the latest available inventory state rather than a history of daily inventory snapshots.

All data types must be verified against the approved Transformation Stage contract before implementation to prevent numerical precision loss or incompatible data conversion.