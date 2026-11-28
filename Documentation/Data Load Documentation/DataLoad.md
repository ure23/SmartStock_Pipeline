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

## 3. Load Strategy and Rules

### 3.1 Load Type and Write Logic

The SmartStock Pipeline uses incremental extraction in Stage 1. However, the proposed Load Stage uses a full snapshot refresh to ensure that the target database reflects the complete and latest approved transformed datasets.

This strategy also prevents outdated records and historical aggregates from remaining in the target database after upstream corrections or deletions.

| Target Table | Load Type | Write Logic | Match Key | On Failure |
| --- | --- | --- | --- | --- |
| dim_product | Full | Replace, SCD Type 1-style | product_id | Roll back batch |
| dim_order | Full | Replace, SCD Type 1-style | order_id | Roll back batch |
| fact_order_item | Full | Delete and reload | order_item_id | Roll back batch |
| fact_inventory_snapshot | Full | Replace latest snapshot | inventory_id | Roll back batch |
| fact_stock_movement | Full | Delete and reload | movement_id | Roll back batch |
| agg_monthly_product_demand | Full | Replace aggregate records | order_month, product_id | Roll back batch |
| agg_monthly_order_sales | Full | Replace aggregate records | order_month | Roll back batch |
| agg_monthly_product_movement | Full | Replace aggregate records | movement_month, product_id | Roll back batch |
| agg_annual_stock_in | Full | Replace aggregate records | movement_year, product_id | Roll back batch |

All approved transformed records are loaded into temporary staging tables before the existing target records are replaced.

Match keys are used to identify new, updated, unchanged, and deleted records relative to the previous accepted snapshot.

### 3.2 Handling of Changing Data

| Condition | Handling Rule |
| --- | --- |
| New records | Include the new records in the approved snapshot and load them into the target tables. |
| Updated records | Replace previous values with the latest approved transformed values. |
| Deleted records | Remove records that are no longer present in the complete approved snapshot. |
| Inactive records | Preserve the product or order status provided by the Transformation Stage. |
| Late-arriving records | Load the corrected records and historical aggregates prepared by the Transformation Stage. |
| Schema mismatch | Reject incompatible schemas and notify the project team. |
| Missing dimension records | Reject the batch and request correction from the Transformation Stage. |

The Load Stage must not modify business values, perform new data cleaning, or recalculate analytical measures.

### 3.3 Load Order and Dependencies

The loading process follows the sequence below:

1. Validate the approved Transformation Stage handover.
2. Load the transformed datasets into temporary staging tables.
3. Validate the staged records and their relationships.
4. Delete existing dependent aggregate and fact records.
5. Delete existing dimension records.
6. Load dim_product and dim_order.
7. Load the fact tables.
8. Load the aggregate tables.
9. Perform post-load validation and reconciliation.
10. Commit the transaction and mark the batch as complete.

Dimension tables must be loaded before dependent fact and aggregate tables to prevent foreign key violations.

### 3.4 Transaction and Rollback Handling

All target table changes must be performed within a single PostgreSQL database transaction.

A database advisory lock must prevent multiple loaders from replacing the warehouse simultaneously.

If any critical validation check or SQL operation fails, the entire transaction must be rolled back. The previous successfully loaded dataset must remain available in the target database.

The failure details must be recorded separately in the load logs after rollback.

### 3.5 Rerun and Idempotency

Each successful batch is identified by a unique batch ID and manifest checksum recorded in the committed-batch registry.

- A batch that has already been successfully loaded with the same checksum must be skipped.
- A failed batch may be rerun using the same approved transformed files and a new load run ID.
- Full snapshot replacement prevents duplicate records and inflated analytical totals.
- An older batch must not overwrite a newer successfully loaded batch.
- A modified handover for an already successful batch requires a new approved correction batch ID.
- If the database connection fails during commit, the committed-batch registry must be checked before retrying.

These rules ensure that repeated execution of the same batch does not create duplicate data or inconsistent reporting results.

## 4. Pre-Load Validation Checks

Pre-load validation ensures that the target database and approved transformed datasets are ready before the loading process begins. These checks prevent incomplete, invalid, incompatible, or duplicate batches from being written to the target database.

| Check ID | Check Name | Target | Purpose | Validation Criteria | Severity |
| --- | --- | --- | --- | --- | --- |
| L-PRE-01 | Target Connection | PostgreSQL database | Ensure the target database is available | Database connection and SELECT 1 succeed within 10 seconds | Critical |
| L-PRE-02 | Write Permissions | Loader account | Ensure authorized database access | Required SELECT, INSERT, DELETE, temporary table, and audit permissions are available | Critical |
| L-PRE-03 | Schema Match | All target tables and CSV files | Prevent incompatible column and data type errors | Required columns, keys, data types, and schema versions match the approved contract | Critical |
| L-PRE-04 | Handover Status | Transformation metadata | Ensure only approved data is loaded | Handover status is APPROVED and batch lineage matches | Critical |
| L-PRE-05 | Handover Completeness | Transformed CSV files | Prevent incomplete snapshot loading | All nine files are present, declared cumulative, and match their checksums | Critical |
| L-PRE-06 | Input Record Count | CSV files and manifest | Detect missing or additional records | Actual record counts equal the approved transformation output counts | Critical |
| L-PRE-07 | Available Storage | Target database and staging storage | Prevent storage-related failures | Available storage is sufficient for staging, target replacement, transaction logs, and metadata | Critical |
| L-PRE-08 | Duplicate Batch Check | Committed-batch registry | Prevent duplicate or outdated loads | Batch has not been successfully loaded and follows the correct batch sequence | Critical |
| L-PRE-09 | Key and Required Field Check | Staged datasets | Prevent duplicate keys and missing required values | Duplicate keys and required null values equal zero | Critical |
| L-PRE-10 | Parent Record Check | Dimension, fact, and aggregate datasets | Prevent foreign key violations | All required foreign keys have corresponding dimension records | Critical |
| L-PRE-11 | Unexpected Empty Dataset | Transformed datasets | Identify unusual data absence | Unexpected zero-record datasets are flagged for review | Non-critical |
| L-PRE-12 | Load Lock | PostgreSQL advisory lock | Prevent concurrent warehouse replacement | Exclusive loading lock is successfully acquired | Critical |

### 4.1 Pre-Load Validation Rules

- All critical validation checks must pass before target records are modified.
- If a critical check fails, the loading process must stop and the failure must be recorded.
- Non-critical warnings require manual review before publication.
- A valid zero-record dataset may be accepted if its absence is documented in the approved transformation handover.
- A missing file must be treated as a critical failure.
- A previously successful batch with an identical manifest checksum must be skipped instead of loaded again.
- A proposed storage reserve of 20% must be considered when evaluating available database capacity.

Only batches that satisfy the pre-load requirements are allowed to proceed to the loading process.

## 5. Post-Load Validation and Reconciliation

Post-load validation ensures that the records written to the target database are complete, accurate, and consistent with the approved transformed datasets.

All critical post-load checks must be performed within the same database transaction before the batch is committed and made available for reporting.

| Check ID | Check Name | Target | Purpose | Validation Criteria | Severity |
| --- | --- | --- | --- | --- | --- |
| L-POST-01 | Record Reconciliation | All target tables | Detect missing or additional records | Records received = records loaded + records rejected; rejected records must equal zero for an accepted batch | Critical |
| L-POST-02 | Target Row Count | All target tables | Verify that all expected records are loaded | Target row count equals the approved input record count | Critical |
| L-POST-03 | Primary Key Uniqueness | All primary and composite keys | Prevent duplicate records | Duplicate key count = 0 | Critical |
| L-POST-04 | Referential Integrity | Fact and aggregate tables | Prevent orphan records | All required foreign keys match existing dimension records | Critical |
| L-POST-05 | Required Field Null Check | Required target columns | Ensure data completeness | Required null value count = 0 | Critical |
| L-POST-06 | Amount Reconciliation | Order totals, item amounts, and monthly sales | Verify monetary accuracy | Target monetary totals equal their corresponding transformed input totals | Critical |
| L-POST-07 | Quantity Reconciliation | Order items, inventory, stock movements, and aggregates | Verify quantity accuracy | Target quantity totals equal their corresponding transformed input totals | Critical |
| L-POST-08 | Key and Value Comparison | All target business columns | Detect missing, additional, or incorrect values | All business keys and values match the staged transformed input | Critical |
| L-POST-09 | Load Error Check | Load logs and database transaction | Ensure loading completed without errors | Unresolved errors, constraint violations, and interruptions equal zero | Critical |
| L-POST-10 | Optional Field Null Check | Nullable target columns | Identify unexpected missing values | Null rates remain within the approved Transformation Stage expectations | Non-critical |
| L-POST-11 | Load Duration Check | Load execution time | Monitor loading performance | Warning at 20 minutes; abort if the 30-minute deadline is exceeded | Non-critical / Critical |

### 5.1 Record Reconciliation Rules

The following formulas are used to verify record completeness and consistency for each target table.

**Record Reconciliation:**

    Records Received = Records Loaded + Records Rejected

**Logical Load Reconciliation:**

    Records Loaded = Records Inserted + Records Updated + Records Unchanged

**Full Snapshot Reconciliation:**

    Target Record Count After Load = Records Loaded

**Target Record Count Reconciliation:**

    Target Count Before Load + Records Inserted - Records Deleted
    = Target Count After Load

Inserted, updated, unchanged, and deleted records are logical classifications based on comparison with the previous accepted snapshot.

Because the Load Stage uses full snapshot replacement, all accepted input records are physically inserted again, including records whose business values have not changed.

Only records rejected during the Load Stage are counted as load rejections. Records already excluded or rejected during the Transformation Stage must not be counted again.

For interrupted or failed batches, rejected, unprocessed, and rolled-back records must be documented separately. Committed record counts are zero when the entire transaction is rolled back.

### 5.2 Aggregate Reconciliation

| Target Table | Validation Measure |
| --- | --- |
| dim_order | SUM(reported_total_amount) |
| fact_order_item | SUM(quantity), SUM(line_amount) |
| fact_inventory_snapshot | SUM(quantity_on_hand) |
| fact_stock_movement | SUM(quantity) |
| agg_monthly_product_demand | SUM(quantity_sold) |
| agg_monthly_order_sales | SUM(order_count), SUM(sales_amount) |
| agg_monthly_product_movement | SUM(quantity_in), SUM(quantity_out) |
| agg_annual_stock_in | SUM(quantity_in) |

Each aggregate measure must be compared with its corresponding approved transformed input. Monetary comparisons must preserve decimal precision.

Reported order totals and order-item line amounts must be reconciled separately because they are not necessarily equivalent.

### 5.3 Validation Handling

If any critical post-load validation check fails, the entire batch must be rolled back and marked as rejected.

If a non-critical warning occurs, the batch must be held for manual review before publication.

No additional data cleaning or business transformation must be performed during the Load Stage. Identified issues must be reported to the appropriate stage for correction.

**Actual Validation Results:** Pending implementation and execution of the Load Stage.