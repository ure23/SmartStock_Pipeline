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