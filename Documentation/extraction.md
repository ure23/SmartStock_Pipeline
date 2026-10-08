# Stage 1: Data Extraction Documentation

## SmartStock Inventory and Delivery Tracking System Analytics Pipeline

**Objective**

The goal of this stage is to extract data from the SmartStock PostgreSQL database using Python and prepare a documented, traceable, and validated dataset containing the required product, inventory, order, order item, and stock movement records for the next stage of the data pipeline.

## 1. Data Source and Extraction Specifications

### 1.1 Source System

**Source System:** SmartStock Inventory and Delivery Tracking System

**Purpose:**

The SmartStock system manages inventory, product/material, order, and stock movement information for Glassram Glass and Aluminum Supply. The records stored in the system will serve as the source data for inventory and transaction analytics.

### 1.2 Source Database or File

**Database Management System:** PostgreSQL

**Source Database:** SmartStock PostgreSQL Database

**File Format:** CSV

PostgreSQL is used as the primary database for structured SmartStock information. The selected source tables contain product/material, inventory, order, order item, and stock movement records required by the analytics pipeline.

### 1.3 Extraction Method

**Extraction Type:** Incremental Extraction

**Extraction Tool:** Python with SQL queries

**Extraction Process:**

Python connects to the SmartStock PostgreSQL database and retrieves newly added or updated records from the selected source tables using the defined extraction field and extraction window. The extracted records are prepared as raw data for validation before proceeding to the Transformation Stage.

**Incremental Extraction Field and Logic:**

The extraction uses the approved date or timestamp field of the source records to identify newly added or updated records since the previous successful extraction run. Only records within the defined extraction window are retrieved.

**Extraction Schedule:**

The extraction is performed as a daily batch process to retrieve newly added or updated SmartStock records for the analytics process.

### 1.4 Extraction Scope

The extraction includes the SmartStock information required by the analytics pipeline.

| Source Table / Data | Extraction Purpose |
|---|---|
| `products_materials` | Retrieve product and material information |
| `inventory` | Retrieve current inventory and stock level information |
| `orders` | Retrieve order and transaction information |
| `order_items` | Retrieve product quantities and item-level transaction information |
| `stock_movements` | Retrieve historical stock movement information |

The extraction covers newly added or updated records within the defined extraction window of each batch run.

### 1.5 Source Limitations and Assumptions

The following limitations and assumptions apply:

- SmartStock records must be available in PostgreSQL before extraction begins.
- Python must be able to establish a valid connection to PostgreSQL.
- Required source tables and columns must exist.
- The incremental extraction depends on the approved date or timestamp field used to identify newly added or updated records.
- The extraction window must be maintained based on the previous successful extraction run.
- Historical records are limited to the data available in the source database.
- Unexpected database schema changes may cause extraction validation to fail.
- Database connectivity problems may interrupt an extraction run.
- The current source schema does not contain dedicated purchase transaction tables for annual purchased-material analysis.

## 2. Source Tables and Column Specification

### 2.1 `products_materials`

**Purpose**

The `products_materials` table contains information identifying and classifying the products and materials managed by SmartStock.

| Column | Data Type | Key / Constraint | Purpose |
|---|---|---|---|
| `product_id` | INT | Primary Key | Unique product/material identifier |
| `product_name` | VARCHAR(150) | — | Product/material name |
| `category` | VARCHAR(100) | — | Product/material category |
| `unit_price` | DECIMAL(12,2) | — | Unit price |
| `reorder_level` | INT | — | Reorder reference level |
| `status` | VARCHAR(30) | — | Product/material status |
| `updated_at` | DATETIME | — | Latest update date and time |

**Reason for inclusion:** Product and material information is required to identify the items used in inventory and transaction analysis.

### 2.2 `inventory`

**Purpose**

The `inventory` table contains the current quantity and inventory status of products and materials.

| Column | Data Type | Key / Constraint | Purpose |
|---|---|---|---|
| `inventory_id` | INT | Primary Key | Unique inventory identifier |
| `product_id` | INT | Foreign Key → products_materials(product_id) | Identifies the related product/material |
| `quantity_on_hand` | INT | — | Current available quantity |
| `reorder_level` | INT | — | Reorder reference level |
| `last_updated` | DATETIME | — | Latest inventory update |

**Reason for inclusion:** Inventory records are required for inventory level monitoring and inventory-related analysis.

### 2.3 `orders`

**Purpose**

The `orders` table contains customer order and transaction information.

| Column | Data Type | Key / Constraint | Purpose |
|---|---|---|---|
| `order_id` | INT | Primary Key | Unique order identifier |
| `customer_id` | INT | Foreign Key | Identifies the related customer |
| `order_date` | DATE | — | Date the order was placed |
| `status` | VARCHAR(30) | — | Current order status |
| `total_amount` | DECIMAL(12,2) | — | Total order amount |

**Reason for inclusion:** Order records are required for monthly sales and transaction analysis.

### 2.4 `order_items`

**Purpose**

The `order_items` table contains the individual products/materials included in each order.

| Column | Data Type | Key / Constraint | Purpose |
|---|---|---|---|
| `order_item_id` | INT | Primary Key | Unique order item identifier |
| `order_id` | INT | Foreign Key → orders(order_id) | Identifies the related order |
| `product_id` | INT | Foreign Key → products_materials(product_id) | Identifies the related product/material |
| `quantity` | INT | — | Quantity ordered |
| `unit_price` | DECIMAL(12,2) | — | Unit price |

**Reason for inclusion:** Order item records are required to analyze product-level transaction quantities and support demand forecasting.

### 2.5 `stock_movements`

**Purpose**

The `stock_movements` table contains records of changes in product/material stock.

| Column | Data Type | Key / Constraint | Purpose |
|---|---|---|---|
| `movement_id` | INT | Primary Key | Unique stock movement identifier |
| `product_id` | INT | Foreign Key → products_materials(product_id) | Identifies the related product/material |
| `movement_type` | VARCHAR(30) | — | Type of stock movement |
| `quantity` | INT | — | Quantity involved in the movement |
| `movement_date` | DATETIME | — | Date and time of the stock movement |
| `reference_id` | INT | — | Reference to the related transaction |

**Reason for inclusion:** Stock movement records are required for monthly inventory movement analysis and fast-moving and slow-moving product classification.

### 2.6 Source Relationships

| Relationship | Description |
|---|---|
| `products_materials → inventory` | One product/material can have inventory records through `inventory.product_id`. |
| `products_materials → order_items` | One product/material can appear in many order item records through `order_items.product_id`. |
| `orders → order_items` | One order can contain many order item records through `order_items.order_id`. |
| `products_materials → stock_movements` | One product/material can have many stock movement records through `stock_movements.product_id`. |

## 3. Extraction Validation and Data Quality Checks

The extraction validation checks are used to verify that the required SmartStock data was successfully accessed, retrieved, and prepared for the succeeding Transformation Stage. The checks focus only on the extraction process and do not include data cleaning, standardization, or business transformations.

### 3.1 Validation Checks

| Check Name | Target | Purpose | Validation Criteria |
|---|---|---|---|
| Source Connection and Accessibility | SmartStock PostgreSQL database | Verify that the source database can be accessed before extraction | The PostgreSQL connection is successfully established |
| Required Tables | `products_materials`, `inventory`, `orders`, `order_items`, `stock_movements` | Verify that all required source tables are available | All required tables are accessible and can be queried |
| Required Columns | Selected columns from the source tables | Verify that the fields required for extraction exist | All documented required columns are present and accessible |
| Required Identifiers | Primary and foreign key columns | Verify that records can be identified and related during extraction | Required identifier columns are present in the extracted data |
| Primary Key Uniqueness | Primary key columns | Verify that source records have unique identifiers | No duplicate primary key values are found within the extracted records |
| Record Count | Source query results and extracted data | Verify that the expected records are retrieved | The number of records extracted matches the records returned by the source extraction query |
| Extraction Completeness | Extraction result | Verify that the incremental extraction was completed for the defined extraction window | All records within the defined extraction window are successfully extracted |
| Extraction Error Check | Python extraction process | Detect errors that occur while retrieving source data | No unhandled extraction errors are encountered |
| Extraction Interruption Check | Extraction run | Verify that the extraction process finishes successfully | The extraction run completes without interruption |

**Scope Limitation:** The validation checks are limited to the extraction stage. Data cleaning, data standardization, duplicate handling, missing-value treatment, and business transformations will be documented in the succeeding Transformation Stage.

## 4. Extraction Metadata and Log Specification

Extraction metadata and logs will be recorded for each extraction run to support monitoring, troubleshooting, auditing, and recovery. The metadata will identify the source table, extraction timing, outcome, record counts, extraction window, and validation status of each run.

| Field Name          | Purpose                                                                 | Example Value / Format         |
| ------------------- | ----------------------------------------------------------------------- | ------------------------------ |
| `pipeline_run_id`   | Uniquely identifies each extraction run.                                | `RUN-20261009-001`             |
| `table_name`        | Identifies the source table being extracted.                            | `products_materials`           |
| `start_timestamp`   | Records when extraction begins.                                         | `2026-10-09 08:00:00`          |
| `end_timestamp`     | Records when extraction finishes.                                       | `2026-10-09 08:00:05`          |
| `extraction_status` | Indicates whether the extraction completed successfully.                | `SUCCESS / FAILED`             |
| `records_read`      | Number of records retrieved by the source query.                        | `250`                          |
| `records_extracted` | Number of records successfully included in the extraction output.       | `250`                          |
| `records_rejected`  | Number of records not included in the extraction output, if applicable. | `0`                            |
| `extraction_window` | Specifies the date or timestamp range covered by the extraction run.    | `Configured extraction window based on the applicable source date/timestamp field` |
| `validation_result` | Records the outcome of extraction validation.                           | `PASS`                  |
| `error_message`     | Documents the error encountered, if any.                                | `NULL`                         |
| `duration`          | Records the total extraction time.                                      | `5 seconds`                    |

The metadata values shown above are examples only. Actual values will depend on the results of each extraction run.

The logs will cover the selected SmartStock source tables: `products_materials`, `inventory`, `orders`, `order_items`, and `stock_movements`.

The extraction will use relevant available data from the selected source tables. Historical transaction and stock movement records will be extracted according to the defined extraction window and the available source data. Product and inventory records will be extracted according to the requirements of the analytics pipeline.

The actual historical data coverage may vary between source tables depending on the records available in the SmartStock PostgreSQL database. The extraction process will not assume that all tables contain the same number of records or cover the same number of years.

For incremental extraction, the extraction window will be based on the applicable source date or timestamp field and the previous successful extraction run. The initial extraction period and subsequent extraction windows will be defined according to the available source data and pipeline configuration.

The metadata and logs will be used to monitor extraction runs, identify failed or incomplete extractions, support troubleshooting, provide an audit trail, and assist in recovery or reruns when an extraction does not complete successfully.

## 5. Log Retention and Access

Extraction logs are proposed to be retained for at least 30 days after each extraction run. This retention period will allow the project team to review recent extraction activity, troubleshoot issues, support auditing, and recover from failed or incomplete extraction runs.

| Requirement            | Specification                                                                                                                                        |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Log Retention Period   | At least 30 days after each extraction run.                                                                                                          |
| Justification          | Allows recent extraction runs to be reviewed for troubleshooting, auditing, and recovery.                                                            |
| Storage Location       | Project-controlled storage designated for ETL pipeline logs.                                                                                         |
| Access Permissions     | Access limited to authorized project team members responsible for the ETL pipeline.                                                                  |
| Archiving Requirements | Logs required for ongoing investigations or audits may be retained beyond the standard retention period.                                             |
| Deletion Rules         | Logs must not be deleted before the end of the defined retention period or while they are still required for troubleshooting, auditing, or recovery. |
| Responsible Process    | The designated ETL or project administrator will manage log retention, archiving, and deletion.                                                      |

Operational extraction logs will follow the defined retention period. Audit records required for longer-term review may be retained beyond 30 days when necessary. Actual storage, access, archiving, and deletion procedures will follow the project's implemented configuration.
