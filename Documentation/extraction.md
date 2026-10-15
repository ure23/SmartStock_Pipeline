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

### 6.1 Required Schema

The extraction data contract defines the expected source tables, fields, data types, and required identifiers and constraints of the SmartStock Inventory and Delivery Tracking System Analytics Pipeline. The source data comes from the SmartStock PostgreSQL database and is prepared for CSV output.

| Source | Expected Fields | Data Types | Required Identifiers and Constraints |
|---|---|---|---|
| `products_materials` | `product_id`, `product_name`, `category`, `unit_price`, `reorder_level`, `status`, `updated_at` | INT, VARCHAR(150), VARCHAR(100), DECIMAL(12,2), INT, VARCHAR(30), DATETIME | `product_id` — Primary Key |
| `inventory` | `inventory_id`, `product_id`, `quantity_on_hand`, `reorder_level`, `last_updated` | INT, INT, INT, INT, DATETIME | `inventory_id` — Primary Key; `product_id` — Foreign Key referencing `products_materials.product_id` |
| `orders` | `order_id`, `customer_id`, `order_date`, `status`, `total_amount` | INT, INT, DATE, VARCHAR(30), DECIMAL(12,2) | `order_id` — Primary Key; `customer_id` — Related Identifier |
| `order_items` | `order_item_id`, `order_id`, `product_id`, `quantity`, `unit_price` | INT, INT, INT, INT, DECIMAL(12,2) | `order_item_id` — Primary Key; `order_id` — Foreign Key referencing `orders.order_id`; `product_id` — Foreign Key referencing `products_materials.product_id` |
| `stock_movements` | `movement_id`, `product_id`, `movement_type`, `quantity`, `movement_date`, `reference_id` | INT, INT, VARCHAR(30), INT, DATETIME, INT | `movement_id` — Primary Key; `product_id` — Foreign Key referencing `products_materials.product_id`; `reference_id` — Related Identifier |

The expected fields and data types must follow the documented source schema. Primary keys identify individual records, while documented foreign keys establish relationships between tables. Related identifiers must be checked against the actual database schema before being treated as foreign keys. Required fields and applicable constraints must be validated during extraction, and any inconsistencies must be recorded in the extraction logs.

## 6.2 Naming Convention

The SmartStock extraction pipeline follows consistent naming rules to maintain readability and consistency across the PostgreSQL source tables, extraction scripts, and CSV output files.

| Naming Rule | Specification |
|---|---|
| Column Naming Format | Use lowercase letters and `snake_case`, where multiple words are separated by underscores. Examples include `product_name`, `quantity_on_hand`, and `movement_date`. |
| Abbreviations | Avoid unnecessary abbreviations and use descriptive names that clearly represent the stored data. Existing source column names should be retained unless a justified mapping is documented. |
| Naming Consistency | Use the same column names consistently in the pipeline documentation, extraction scripts, and corresponding CSV output fields. |
| Primary Key Naming | Use the entity name followed by `_id`, such as `product_id`, `inventory_id`, `order_id`, `order_item_id`, and `movement_id`. |
| Foreign Key Naming | Use the referenced entity name followed by `_id` when a foreign-key relationship exists. Examples include `product_id` in `inventory` and `order_items`, and `order_id` in `order_items`. |

These naming conventions help ensure that extracted fields remain identifiable and consistent throughout the pipeline. Any approved changes to field names must be documented in the source-to-standardized field mapping.

## 6.3 Source-to-Standardized Field Mapping

The source-to-standardized field mapping documents how source columns are represented in the extracted datasets. The SmartStock pipeline retains the documented source column names and data types unless a justified and documented transformation is required. The following table shows representative mappings from the five source tables.

| Source Column | Standardized Column | Source Type | Target Type | Mapping Type |
|---|---|---|---|---|
| `products_materials.product_id` | `product_id` | INT | INT | Direct mapping |
| `products_materials.product_name` | `product_name` | VARCHAR(150) | VARCHAR(150) | Direct mapping |
| `products_materials.unit_price` | `unit_price` | DECIMAL(12,2) | DECIMAL(12,2) | Direct mapping |
| `inventory.inventory_id` | `inventory_id` | INT | INT | Direct mapping |
| `inventory.quantity_on_hand` | `quantity_on_hand` | INT | INT | Direct mapping |
| `orders.order_id` | `order_id` | INT | INT | Direct mapping |
| `orders.order_date` | `order_date` | DATE | DATE | Direct mapping |
| `orders.total_amount` | `total_amount` | DECIMAL(12,2) | DECIMAL(12,2) | Direct mapping |
| `order_items.order_item_id` | `order_item_id` | INT | INT | Direct mapping |
| `order_items.quantity` | `quantity` | INT | INT | Direct mapping |
| `stock_movements.movement_id` | `movement_id` | INT | INT | Direct mapping |
| `stock_movements.movement_date` | `movement_date` | DATETIME* | DATETIME* | Direct mapping |

The standardized column names must remain consistent throughout the extraction documentation, scripts, and output datasets. If a source column is renamed or its data type is converted, the mapping must be updated to identify the source field, standardized field, source type, target type, and mapping operation.

**Note:** The data types in this table are based on the existing pipeline documentation and must be verified against the actual PostgreSQL schema and CSV output requirements. The table provides representative examples rather than a complete mapping of every column.

### 6.4 Schema Consistency

The extraction process will check whether the source tables, column names, data types, and required identifiers match the documented schema. Unexpected changes will be handled as follows:

- **Column Name Changes:** If a required column is renamed or unavailable, the issue will be flagged and recorded in the extraction log. Extraction will not proceed if the affected column is necessary for the process.
- **Data Type Changes:** If a column's data type differs from the documented schema, the change will be flagged for review to determine its effect on extraction and the expected output.
- **Missing Required Fields:** If a required column or identifier is missing, schema validation will fail, and the issue will be recorded in the extraction log.
- **Unexpected Additional Columns:** Additional columns will not automatically be included in the output unless they are reviewed and approved.
- **Approved Schema Changes:** Approved changes will be documented and reflected in the Python extraction script when necessary.

Schema validation results and related errors will be recorded in the extraction logs to maintain consistency between the source database, extraction script, and output dataset.

# 7. Extraction Acceptance and Handover Rules

The extraction stage must validate the extracted data before passing it to the Transformation Stage. These rules define the conditions for accepting, reviewing, or rejecting the extracted data to ensure that it is complete, accessible, and ready for the next stage.

## 7.1 Automatic Approval

The extracted data can proceed automatically when all critical validation checks pass.

- All five required source tables are accessible: `products_materials`, `inventory`, `orders`, `order_items`, and `stock_movements`.
- All required columns and identifiers are present.
- Primary key values are unique within the extracted records.
- The extracted record counts match the results returned by the source extraction queries.
- The extraction completes successfully within the defined extraction window.
- All required CSV output files are generated and readable.
- No critical extraction errors are encountered.

When all these conditions are met, the extraction status will be marked as **APPROVED**, and the data can proceed to the Transformation Stage.

## 7.2 Manual Review

Manual review is required when non-critical warnings or unexpected results need further investigation.

Examples include:

- The extracted record count differs from the expected count and requires verification.
- Unexpected additional columns are found in the source schema.
- Non-critical warnings appear in the extraction logs.
- Unexpected results require confirmation before the data can proceed.

The pipeline must hold the affected data until an authorized team member reviews the issue. The reviewer must document the findings and decide whether the data can be accepted or must be extracted again.

**Responsible Role:** Assigned ETL Team Member or designated project team member.

## 7.3 Rejection or Failure

The extracted data must be rejected when a critical issue prevents it from meeting the required validation conditions.

Examples include:

- The SmartStock PostgreSQL database cannot be accessed.
- A required source table or column is missing or inaccessible.
- A required identifier is missing or primary key values are duplicated.
- The extraction fails before all required records are retrieved.
- A required CSV output file is missing, incomplete, or unreadable.
- A critical extraction error prevents the data from being validated.

When a critical failure occurs, the pipeline must stop the handover process and record the error in the extraction log. The extraction may be retried if the problem is temporary. If the problem persists, the pipeline must remain stopped until the issue is resolved. Failed or incomplete data must not proceed to the Transformation Stage.

## 7.4 Handover

After the extraction is approved, the extracted data and its supporting records will be prepared for the Transformation Stage.

The handover must include:

- **Extracted Data:** CSV output files containing records from `products_materials`, `inventory`, `orders`, `order_items`, and `stock_movements`.
- **Extraction Metadata:** Pipeline run ID, source table name, start and end timestamps, extraction status, record counts, and extraction window.
- **Validation Results:** Results of the required table, column, identifier, primary key uniqueness, record count, and extraction completeness checks.
- **Extraction Logs:** Records of successful operations, warnings, errors, and actions taken to resolve issues.
- **Handover Status:** The final acceptance decision indicating whether the extracted data is approved to proceed to the Transformation Stage.

The receiving stage must verify that the required output files and supporting records are available. Data cleaning, standardization, and business transformations will be handled in the Transformation Stage.

## 7.5 Decision Rules

| Overall Condition | Acceptance Decision | Pipeline Action |
|---|---|---|
| All required tables PASS | APPROVED | Proceed to Transformation |
| One or more non-critical WARNING | MANUAL REVIEW | Hold pipeline |
| One or more critical FAIL | REJECTED | Stop/retry extraction as appropriate |

## 7.6 Validation Summary

| Validation Summary | Expected Result |
|---|---|
| `products_materials` table validation | PASS |
| `inventory` table validation | PASS |
| `orders` table validation | PASS |
| `order_items` table validation | PASS |
| `stock_movements` table validation | PASS |
| Required columns and identifiers validation | PASS |
| Primary key uniqueness validation | PASS |
| Record count validation | PASS |
| Extraction completeness validation | PASS |
| CSV output file validation | PASS |
| **Overall Extraction** | **APPROVED** |

The expected results above describe the conditions required for successful extraction. Actual validation results must be recorded after the extraction process runs. If any critical check fails or a non-critical warning requires investigation, the overall extraction decision must follow the rules defined in Section 7.5.

The acceptance and handover rules described in this section will serve as implementation requirements for the extraction pipeline. The validation checks, decision handling, and handover procedures will be implemented and verified during development.

# 8. Common Extraction Problems and Mitigation

The extraction process may encounter technical problems when retrieving data from the SmartStock PostgreSQL database and generating CSV output files. The following problems, possible causes, impacts, and proposed solutions are identified to help maintain the completeness and reliability of the extracted data.

## 8.1 Common Extraction Problems

| Problem Description | Possible Cause | Impact on the Extraction Process | Proposed Solution or Mitigation |
|---|---|---|---|
| Database Connection Failure | Incorrect database credentials, unavailable PostgreSQL server, or network connectivity problems. | The Python script cannot access the source database, preventing data extraction. | Verify the database connection settings, credentials, server availability, and network connection before rerunning the extraction. |
| Missing Source Table or Column | A required table or column has been renamed, removed, or changed in the SmartStock database. | The extraction query may fail or retrieve incomplete data, preventing successful validation. | Validate the required tables and columns before extraction. Record the error and update the extraction script and documentation when an approved schema change occurs. |
| Incorrect or Incomplete Incremental Extraction | The extraction window or date/timestamp field is configured incorrectly, or records are updated outside the selected extraction window. | Newly added or updated records may be omitted, resulting in incomplete data for the analytics pipeline. | Review the extraction window and applicable source date/timestamp fields. Compare extracted record counts with source query results and rerun the affected extraction when necessary. |
| Duplicate Records in Extracted Data | The extraction query returns repeated records, or the extraction window overlaps with a previous run. | Duplicate records may affect record counts and cause inaccuracies in subsequent analysis if not identified. | Check primary key uniqueness during validation and review the extraction query and window configuration. Resolve the cause before approving the affected data. |
| CSV Output Generation Failure | The output directory is unavailable, the Python process lacks write permission, or an error occurs while writing the file. | One or more required CSV files may be missing, incomplete, or unreadable. | Verify the output directory and write permissions. Regenerate the affected files and confirm that they are readable before proceeding to the Transformation Stage. |
| Data Type or Format Inconsistency | Source values do not match the documented schema, or date, timestamp, and numeric values are exported in inconsistent formats. | The extracted output may fail validation or cause parsing problems during the Transformation Stage. | Check source data types and CSV output formats. Record unexpected differences, review their effects, and resolve critical issues before approving the extraction. |
| Extraction Interruption | The Python process stops unexpectedly, the database connection is lost, or the extraction encounters an unhandled error. | The extraction may stop before all required records are retrieved or output files are completed. | Record the error in the extraction log, verify which outputs are incomplete, and rerun the extraction after resolving the cause. Do not hand over incomplete data. |

## 8.2 Problem Handling and Recovery

When an extraction problem occurs, the Python process should record the error and the affected source table or output file in the extraction log whenever possible. The team must determine whether the issue can be resolved by correcting the connection settings, reviewing the extraction query, adjusting the extraction window, or regenerating the output file.

After resolving the problem, the affected extraction must be repeated when necessary. The required validation checks must be performed again before the extracted data is approved for the Transformation Stage. Data affected by unresolved critical problems must not proceed to the next stage.