# Stage 2: Data Transformation Documentation

**Project:** SmartStock: An Inventory and Delivery Tracking System with AI-Assisted Analytics  
**Pipeline stage:** Stage 2 — Transformation  
**Documentation status:** Stage 2 design documentation; the SmartStock Stage 1 incremental runner and daily schedule are implemented. Transformation execution remains outside this repository's Stage 1 scope.
**Related document:** `Extraction/extraction.md` (Stage 1)

## Objective

The objective of this stage is to transform the validated datasets handed over by the SmartStock Extraction Stage into cleaned, standardized, and business-ready datasets. This stage documents data profiling, cleaning, standardization, joins, derived values, aggregations, output contracts, validation, logs, and the criteria for handing approved outputs to the Load Stage. It does **not** retrieve data directly from PostgreSQL or load transformed data into the final target database.

> **Implementation alignment note:** Stage 1 runs daily at 02:00 Asia/Manila through the content-hash incremental runner, after an initial full baseline. Each run compares a repeatable-read PostgreSQL snapshot with database-resident primary-key/content-hash state, exports only new/changed rows, and writes deleted-key tombstones. The Stage 1 handover root is `~/.local/share/smartstock-pipeline/handover/`; each immutable `batch-<YYYYMMDDTHHMMSS+0800>/` directory includes the five table CSVs, `deletions.csv`, `extraction_metadata.json`, and `handover_ready.json`. The ready marker is the handover acceptance gate: Stage 2 must ignore batches without a valid marker. The extraction window is `initial_baseline` or `content_changes_since:<previous_run_id>`; the recorded last-successful run/time is not a source-date cutoff. Every run scans all source rows for changes, so the method detects only changes visible in the selected PostgreSQL snapshot, not changes missing from the external source. Batch outputs are owner-restricted and retained without automatic deletion. Stage 1 does not invoke Stage 2.

## 1. Transformation Input and Processing Specification

### 1.1 Input Source

Stage 2 receives the **validated handover output** of Stage 1, rather than querying the SmartStock source database again. A processable batch contains the five table CSVs, `deletions.csv` tombstones, `extraction_metadata.json`, and a valid `handover_ready.json`. The first batch is a full baseline; subsequent table CSVs contain only new/changed rows, so Stage 2 must apply updates by primary key and apply tombstones to its cumulative reference state. Stage 2 must ignore any directory without the marker or whose marker run ID does not match its manifest.

| Validated Stage 1 dataset | Fields expected from extraction contract | Use in transformation |
| --- | --- | --- |
| `products_materials` | `product_id`, `product_name`, `category`, `unit_price`, `reorder_level`, `status`, `updated_at` | Product descriptions and categories; product lookup |
| `inventory` | `inventory_id`, `product_id`, `quantity_on_hand`, `reorder_level`, `last_updated` | Latest on-hand quantities and stock-level analysis |
| `orders` | `order_id`, `customer_id`, `order_date`, `status`, `total_amount` | Order dates, statuses, and order-level references |
| `order_items` | `order_item_id`, `order_id`, `product_id`, `quantity`, `unit_price` | Item-level quantities and sales amounts |
| `stock_movements` | `movement_id`, `product_id`, `movement_type`, `quantity`, `movement_date`, `reference_id` | Quantified inward/outward stock movements |
| `deletions.csv` | `table_name`, `record_id` | Remove source keys from cumulative Stage 2 reference state |

**Stage 1 handover layout:**

```text
~/.local/share/smartstock-pipeline/
  handover/
    batch-<YYYYMMDDTHHMMSS+0800>/
      products_materials.csv
      inventory.csv
      orders.csv
      order_items.csv
      stock_movements.csv
      deletions.csv
      extraction_metadata.json
      handover_ready.json
  logs/
```

The Stage 2 `parent_run_id` references the Stage 1 `pipeline_run_id` in `extraction_metadata.json` and must match `handover_ready.json`. Copy the Stage 1 `extraction_window` exactly; do not invent or enlarge it. Current run IDs use the `RUN-<uuid>` format. The extraction window is `initial_baseline` or `content_changes_since:<previous_run_id>` and has no source timestamp boundaries.

Stage 2 starts only for a batch with a `handover_ready.json` whose `pipeline_run_id` matches the metadata manifest, and whose required files are readable. The marker means Stage 1 technical extraction/schema/relationship validation and run logging completed; it is not a business approval or a claim of external-source completeness. Stage 2 retains its own profiling, data-quality review, and acceptance decision.

### 1.2 Batch Processing Method

| Item | Specification |
| --- | --- |
| Tool/technology | Proposed Python batch transformation using `pandas` for CSV profiling, cleaning, joining, and aggregation; built-in Python logging/JSON for run manifests |
| Frequency | Stage 1 batches run daily; Stage 2 is not automatically triggered and should process validated batches through an approved consumer |
| Schedule | Stage 1 runs at 02:00 Asia/Manila; Stage 2 may begin only after a ready marker is published |
| Batch window | The `extraction_window` recorded in the accepted Stage 1 metadata, including any initial-baseline indicator |
| Processing unit | One Stage 1 validated batch: five table CSVs, `deletions.csv`, extraction metadata, and the matching readiness marker, plus approved historical reference state required for incremental joins |
| Retry approach | Reprocess the same validated input and same rule version, using a new attempt number linked to the same batch; retain failure logs |
| Idempotency | Replace the **same batch's temporary/output files atomically** (rather than append), and use stable source identifiers for deduplication. The same batch and rule version must not create repeated rows or multiply totals. |

Because an incremental `order_items` file may not contain its parent `orders` row (or a product row), Stage 2 uses the **latest previously approved cumulative reference state** plus applicable incremental updates. This reference state must be established using the initial baseline and previously accepted increments, and retained as an approved pipeline artifact; Stage 2 does not requery PostgreSQL. If required parent rows are unavailable, related records are quarantined or the batch is held for review rather than silently discarded.

**Cumulative-state requirement:** The initial baseline and previously approved incremental records must be combined by source primary key to provide the latest approved state; apply each new/changed row as an upsert and each `deletions.csv` row as a keyed removal. Incremental files alone are **not** sufficient for lifetime/monthly summaries or parent lookups. Persist this state as a controlled Stage 2 working reference or receive it as an approved historical handover, without querying PostgreSQL. Apply each changed source key as an update, not an additional historical sale.

**Late changes:** If an older order or stock-movement record is updated and included in a later incremental batch, recompute the affected output keys and affected monthly aggregates using the approved historical state. For an order-date or order-status change, recompute both the original affected reporting month (when known) and the new reporting month. Do not treat the incremental batch alone as the whole historical dataset.

### 1.3 Transformation Scope

| Dataset | Cleaning/standardization | Business-ready outputs |
| --- | --- | --- |
| `products_materials` | Clean product name/category; validate price, identifier, and date | `dim_product` |
| `inventory` | Validate nonnegative quantity, product reference, and update date | `fact_inventory_snapshot` |
| `orders` | Validate order identifier/date/status/amount; use approved order total for monthly sales reporting | `dim_order`, `agg_monthly_order_sales` |
| `order_items` | Validate quantity and unit price; join to order and product; calculate line amount | `fact_order_item`, `agg_monthly_product_demand` |
| `stock_movements` | Validate direction, quantity, date, and product reference; standardize recognized movement codes | `fact_stock_movement`, `agg_monthly_product_movement`, `agg_annual_stock_in` |

### 1.4 Dependencies and Assumptions

1. Process approved Stage 1 input and metadata first, followed by product and order reference data, then inventory and transactional facts, then aggregations.
2. Required keys must be stable across Stage 1 and Stage 2. No assumed source values are generated for missing source identifiers.
3. Each source table may arrive incrementally; historical reference state used for joins and aggregate recomputation must be available and versioned.
4. The source `orders.status` and `stock_movements.movement_type` permitted values must be confirmed from the SmartStock implementation before finalizing status filters and code mappings.
5. The business uses Philippine pesos (PHP) as the proposed reporting currency; the project must confirm that monetary fields are consistently stored in PHP. Prices/amounts must not be replaced with invented values.
6. An inventory snapshot is the available quantity **as of its recorded update**, not a reconstruction of inventory at every past date.
7. `stock-in` records do not necessarily prove a supplier **purchase**; annual stock-in quantity must not be labeled “annual purchased materials” without a verified purchase/source-type field.

## 2. Data Profiling and Issue Identification

Before executing any cleaning rule, Stage 2 profiles the validated CSV batches and records per-column null counts, distinct counts, unexpected data types/formats, duplicate identifier counts, out-of-range counts, and unmatched foreign keys. **No actual CSV rows or executed profiling report were supplied for this document; actual counts and percentages must be measured during the first implemented run.** The values in the *Example to investigate* column are hypothetical test samples, not observations from SmartStock.

| Table/column | Issue type | Example to investigate (illustrative) | Affected records | Planned treatment |
| --- | --- | --- | --- | --- |
| `products_materials.product_name` | Leading/trailing spaces or blank value | `"  Clear Glass  "`, `""` | **Pending profiling** | C-01, C-02 |
| `products_materials.unit_price` | Invalid negative price | `-150.00` | **Pending profiling** | C-03 |
| `products_materials.product_id` | Duplicate key in handover/reference merge | Same `product_id` appearing twice | **Pending profiling** | C-04 |
| `inventory.quantity_on_hand` | Missing/negative quantity | `NULL`, `-3` | **Pending profiling** | C-05 |
| `inventory.product_id` | Orphan reference | Product ID absent from approved product state | **Pending profiling** | C-06 |
| `orders.order_date` | Unparseable date | `31/31/2026` | **Pending profiling** | S-01 |
| `orders.status` | Missing/unrecognized code | `"unknown-code"` | **Pending profiling** | C-07, S-04 |
| `orders.total_amount` | Missing or negative recorded order amount | `NULL`, `-100.00` | **Pending profiling** | C-12, S-03 |
| `order_items.quantity` | Zero/negative quantity | `0`, `-2` | **Pending profiling** | C-08 |
| `order_items.unit_price` | Missing/negative price | `NULL`, `-20` | **Pending profiling** | C-09 |
| `order_items.order_id`, `product_id` | Missing parent reference | ID not found in approved order/product state | **Pending profiling** | C-06 |
| `stock_movements.movement_type` | Nonstandard/unrecognized code | `" IN "`, `"???"` | **Pending profiling** | S-05 |
| `stock_movements.quantity` | Zero quantity or ambiguous negative sign | `0`, `-5` | **Pending profiling** | C-10 |
| Dates/numerics in all CSVs | Conversion problems | `"not-a-date"`, `"12x"` | **Pending profiling** | S-01, S-02, S-03 |

The implemented profiler must fill each “Pending profiling” field with a measured value in the form `affected_count / total_records (percent)`; if none are affected, write `0 / N (0%)`. Percent = `100 × affected_count / total_records`, with zero-row batches reported separately. Every activated C/S rule should correspond to a confirmed issue category or an explicitly labeled preventive validation check.

## 3. Data Cleaning Rules

All modifications, exclusions, duplicate resolutions, and rejections must be traceable by `rule_id`, input row key, batch ID, and reason. No record may be silently deleted.

| Rule ID / name | Target | Condition | Action | Justification |
| --- | --- | --- | --- | --- |
| **C-01 Trim text** | `products_materials.product_name`, `.category`; `orders.status`; `stock_movements.movement_type` | Leading or trailing whitespace | Trim whitespace; count modified rows | Avoid mismatches in display, grouping, and code matching |
| **C-02 Required product name** | `products_materials.product_name` | Null or empty after trimming | Quarantine row; do not fabricate a name | Product dimension requires a meaningful label |
| **C-03 Nonnegative product price** | `products_materials.unit_price` | Null, nonnumeric, or less than zero | Quarantine row and log | Avoid invalid price and business calculations |
| **C-04 Duplicate key resolution** | Each table's source primary key | Duplicate within batch or merged incremental reference state | Keep the **latest reliably timestamped** version if a valid update timestamp exists; if conflicting records lack reliable ordering, quarantine conflict for manual review. Log all displaced/conflicting rows. | Prevent double counts and arbitrary overwrites |
| **C-05 Valid inventory quantity** | `inventory.quantity_on_hand` | Null, nonnumeric, or negative | Quarantine record | Prevent invalid stock snapshots |
| **C-06 Orphan relationship** | `inventory.product_id`, `order_items.order_id` / `.product_id`, `stock_movements.product_id` | Linked parent ID absent from approved reference state | Try the approved reference snapshot; otherwise quarantine with missing-parent reason | Avoid invalid fact-to-dimension links |
| **C-07 Missing/unrecognized order status** | `orders.status` | Blank or not found in configured allowed values | Quarantine pending source-code review | Do not assign a false business state |
| **C-08 Positive order quantity** | `order_items.quantity` | Null, noninteger (if whole units), zero or negative | Quarantine unless valid fractional units are explicitly authorized in source contract | Preserve correct demand quantities |
| **C-09 Valid order-item price** | `order_items.unit_price` | Null, nonnumeric, or negative | Quarantine | Prevent invented line amounts |
| **C-10 Valid movement quantity** | `stock_movements.quantity` | Missing, nonnumeric, or zero; negative sign has undocumented meaning | Quarantine missing/invalid values; accept signed negative values only if the actual source convention is confirmed and normalized under B-07, otherwise hold for review | Prevent incorrect movement totals without assuming all source quantities are positive |
| **C-11 Invalid control characters** | Text fields | Unsupported control characters | Remove only non-meaningful control characters; keep ordinary printable and international characters; log changes | Maintain readable, safe structured output |
| **C-12 Valid order total** | `orders.total_amount` | Null, invalid numeric representation, or negative amount | Quarantine for sales reporting or hold affected order for review; do not replace with the line sum by assumption | Recorded order total is the documented basis of monthly sales value |

**Missing-value policy:** Reject/quarantine rows when required identifiers, quantities, prices, valid dates, or required join references are missing; preserve nullable optional fields where the output contract allows them (for example, `stock_movements.reference_id`). Never replace unknown business facts with `0`, the current date, or an assumed status.

**Duplicate policy:** Source IDs are the deduplication key: `product_id`, `inventory_id`, `order_id`, `order_item_id`, and `movement_id`. `products_materials.updated_at` and `inventory.last_updated` can help order versions; for tables without a reliable update timestamp in the documented handover, conflicting duplicate values must **not** be resolved by guessing which is newest. Exact identical duplicate copies can be collapsed with a logged duplicate count.

## 4. Standardization and Data Type Rules

| Rule ID | Column(s) | Input representation | Standard output | On failure |
| --- | --- | --- | --- | --- |
| **S-01 Date/time** | `orders.order_date`, `stock_movements.movement_date`, `products_materials.updated_at`, `inventory.last_updated` | CSV date/time strings | Valid date (`YYYY-MM-DD`) for `orders.order_date`; timestamp (`YYYY-MM-DD HH:MM:SS`) for PostgreSQL `TIMESTAMP`-based fields; include an offset only when the source actually provides a timezone-aware timestamp | Quarantine row and log parse error |
| **S-02 Quantities** | `order_items.quantity`, `stock_movements.quantity`, `inventory.quantity_on_hand`, reorder levels | Numeric/text representation | `INTEGER` where whole units are required by source; no silent rounding of fractions | Quarantine invalid conversion |
| **S-03 Monetary data** | Product/order-item prices, `orders.total_amount` | Numeric/text representation | `DECIMAL(12,2)` for recorded monetary fields; use fixed decimal arithmetic and `ROUND_HALF_UP` only when computing derived monetary amounts | Quarantine invalid conversion; review values exceeding precision |
| **S-04 Order status** | `orders.status` | Source codes with possible spacing/case differences | Canonical values from a **verified source status mapping** (trim and normalize for lookup; preserve source code for lineage) | Quarantine unknown status |
| **S-05 Stock movement type** | `stock_movements.movement_type` | Source code variants | Source-approved canonical `IN` / `OUT` values **only where meaning is verified** | Quarantine unmapped value |
| **S-06 Product category** | `products_materials.category` | Category display text | Trim and apply approved category mapping; do not merge distinct categories by guesswork | Keep original and flag for review when mapping unavailable |
| **S-07 Identifier formatting** | All source primary/foreign keys | CSV value (may be text or numeric) | INTEGER identifier consistent with Stage 1, without floating-point parsing or loss of precision | Quarantine missing/unparseable required IDs |

**Time zone:** The business operates in the Philippines. A PostgreSQL `TIMESTAMP` value without a time zone must not be assigned a UTC or Manila offset by guesswork. Confirm source timestamp semantics first; then use one documented reporting timezone when deriving month/year, recorded in the transformation metadata.

**Precision:** Use decimal arithmetic for currency, not binary floating-point. Keep unrounded intermediate arithmetic where practicable and round monetary output to two decimal places. For measurements sold in fractional units, change quantity type only after verifying the underlying contract.

**Reference values:** Currency code `PHP` applies only to verified Philippine-peso monetary fields. Unit of measure is not in the listed extracted columns; **do not create or convert physical units** in Stage 2 without verified unit data. No country/region conversion is required by this dataset.

## 5. Business Transformation Rules

Business transformations run after cleaning and standardization. All rule-level output counts are recorded. Differentiate quantities **sold in order items** from **stock-outward movement** quantities; they are not automatically equivalent.

| Rule ID | Input columns | Transformation logic | Output column/dataset | Business reason |
| --- | --- | --- | --- | --- |
| **B-01 Line amount** | `order_items.quantity`, `order_items.unit_price` | `line_amount = quantity * unit_price`, rounded to 2 decimal places | `fact_order_item.line_amount` | Item-level sales value |
| **B-02 Order-to-item join** | `order_items.order_id`, `orders.order_id` | Many-to-one join to approved `dim_order` state; unmatched item quarantined | `fact_order_item.order_id`, `order_date`, `order_status` | Correct date and status per item |
| **B-03 Product lookup** | `order_items.product_id`, `products_materials.product_id` | Many-to-one join to approved `dim_product` | `fact_order_item.product_id` | Group demand by product/category |
| **B-04 Reporting period** | `orders.order_date`, `stock_movements.movement_date` | Extract year/month after validated timezone treatment | `order_month`, `movement_month`, `movement_year` | Monthly/annual summaries |
| **B-05 Monthly product demand** | `fact_order_item.quantity`, `order_month`, `product_id`, order status | Sum item quantity by month/product for **source-verified qualifying sales statuses**; record excluded counts | `agg_monthly_product_demand.quantity_sold` | Supports fast/slow-moving based on quantity sold and forecasting-ready history |
| **B-06 Monthly sales** | `dim_order.reported_total_amount`, `order_date`, verified qualifying order status | Group by month; sum validated `orders.total_amount` **once per eligible order** and count distinct eligible `order_id` values; do not sum line amounts as a replacement for the recorded order total | `agg_monthly_order_sales.sales_amount`, `order_count` | Monthly sales and transaction trends |
| **B-07 Movement direction** | `stock_movements.movement_type`, `quantity` | Assign verified `IN`/`OUT` direction and a positive `quantity` measure only after confirming whether the source stores signed or unsigned movement quantities | `fact_stock_movement.movement_direction` | Separate receipts from outward movements |
| **B-08 Monthly movement summary** | `fact_stock_movement.movement_month`, `product_id`, `movement_direction`, `quantity` | Sum quantities by month/product/direction | `agg_monthly_product_movement.quantity_in`, `.quantity_out` | Monthly inventory-movement monitoring |
| **B-09 Annual stock-in** | `fact_stock_movement.movement_year`, `product_id`, `movement_direction`, `quantity` | Sum **IN** quantities by year/product | `agg_annual_stock_in.quantity_in` | Monitor inward materials; **not verified purchase volume** |
| **B-10 Stock level** | `inventory.quantity_on_hand`, `inventory.reorder_level` | If quantity = 0 → `OUT_OF_STOCK`; otherwise if a valid reorder level is absent → `UNCLASSIFIED`; otherwise if quantity <= configured reorder level → `LOW_STOCK`; else → `IN_STOCK` | `fact_inventory_snapshot.stock_level` | Consistent stock-level monitoring; confirm threshold in app configuration |
| **B-11 Fast/slow classification** | `agg_monthly_product_demand.quantity_sold` | Compare monthly quantity sold with **documented, approved threshold**; report no-sales separately if defined | `agg_monthly_product_demand.movement_class` | Classify demand velocity, **not current stock quantity** |

**Sales eligibility rule:** The source extraction contract lists `orders.status` but does not establish the source's definitive completed/paid/cancelled status codes. An order with a missing/invalid `total_amount` must not contribute an assumed zero or line-derived value to monthly sales. Before implementing B-05 and B-06, the developer must document which order statuses count as realized sales. Until confirmed, outputs may be produced as **provisional order-activity summaries** but must not be presented as verified completed sales. Record exclusions by reason and status. No status code is invented in this document.

**Threshold for fast/slow movement:** The business must approve a measurable classification basis (for example, a defined quantity-sold threshold or ranking within an established monthly product population). Until approved, leave `movement_class` null or `UNCLASSIFIED`; do not invent a threshold or label a stock-out as a fast seller.

**Annual purchased-materials limitation:** The available Stage 1 columns identify `movement_type` and `quantity` but do not by themselves prove which incoming movements were supplier purchases. `agg_annual_stock_in` is a defensible current output. To satisfy the separate SmartStock objective of annual **purchased materials**, the project must confirm that an existing movement code specifically identifies purchases or add an approved purchase transaction/source field through a revised extraction contract. Do not relabel all stock-in as purchases.

**Historical demand forecasting handover:** `agg_monthly_product_demand` is the cleaned monthly history that a future SES-based statistical forecasting module can consume. **SES forecasting itself is not performed in this transformation stage** unless separately specified in the analytics workflow. AI-assisted explanations/recommendations are likewise outside the Stage 2 cleaning contract.

**Joins, filtering, and change handling:** Use many-to-one joins on `order_id` and `product_id`. Confirm uniqueness on the parent side before joining, and fail validation if join cardinality multiplies rows. Preserve raw status evidence in `dim_order`. Excluded non-eligible orders remain traceable and are counted; other fact rows are not silently erased. Update or replace affected aggregates when historical source rows change.

**Dimensional approach:** Use stable **source/business identifiers** as keys in this Stage 2 proposal rather than introducing unneeded surrogate keys. A future warehouse may introduce surrogate keys in the Load Stage if justified. Product/order descriptive state is treated as latest-known (Type 1-style replacement) unless history requirements are formally approved; do not claim historical category changes were preserved without snapshots.

## 6. Transformed Data Contract and Naming Convention

### 6.1 Required Output Schemas

The following are **proposed Stage 2 output structures** for downstream loading. `NOT NULL` applies to every column marked `required`; nullable values are marked `optional`. Types are logical/SQL target types and may be stored in CSV with a companion schema manifest.

| Output table | Columns and target types | Keys / constraints |
| --- | --- | --- |
| `dim_product` | `product_id` INTEGER **required**; `product_name` VARCHAR **required**; `category` VARCHAR **optional**; `unit_price` DECIMAL(12,2) **required**; `reorder_level` INTEGER **optional**; `product_status` VARCHAR **optional**; `updated_at` TIMESTAMP **optional** | PK `product_id`; nonnegative price/reorder level |
| `dim_order` | `order_id` INTEGER **required**; `customer_id` INTEGER **optional**; `order_date` DATE **required**; `order_status` VARCHAR **required**; `reported_total_amount` DECIMAL(12,2) **optional** | PK `order_id`; valid mapped status |
| `fact_order_item` | `order_item_id` INTEGER **required**; `order_id` INTEGER **required**; `product_id` INTEGER **required**; `order_date` DATE **required**; `order_status` VARCHAR **required**; `quantity` INTEGER **required**; `unit_price` DECIMAL(12,2) **required**; `line_amount` DECIMAL(12,2) **required** | PK `order_item_id`; FK `order_id` → `dim_order`; FK `product_id` → `dim_product`; quantity > 0 |
| `fact_inventory_snapshot` | `inventory_id` INTEGER **required**; `product_id` INTEGER **required**; `quantity_on_hand` INTEGER **required**; `reorder_level` INTEGER **optional**; `last_updated` TIMESTAMP **optional**; `stock_level` VARCHAR **optional** | PK `inventory_id` for latest-state output; FK `product_id` → `dim_product` |
| `fact_stock_movement` | `movement_id` INTEGER **required**; `product_id` INTEGER **required**; `movement_date` TIMESTAMP **required**; `movement_month` CHAR(7) **required**; `movement_year` INTEGER **required**; `movement_direction` VARCHAR **required**; `quantity` INTEGER **required**; `reference_id` INTEGER **optional** | PK `movement_id`; FK `product_id` → `dim_product`; normalized quantity > 0; direction in source-approved `{IN, OUT}` |
| `agg_monthly_product_demand` | `order_month` CHAR(7) **required**; `product_id` INTEGER **required**; `quantity_sold` INTEGER **required**; `movement_class` VARCHAR **optional** | Composite PK (`order_month`, `product_id`); product FK; quantity ≥ 0 |
| `agg_monthly_order_sales` | `order_month` CHAR(7) **required**; `order_count` INTEGER **required**; `sales_amount` DECIMAL(12,2) **required** | PK `order_month`; counts/amounts ≥ 0 |
| `agg_monthly_product_movement` | `movement_month` CHAR(7) **required**; `product_id` INTEGER **required**; `quantity_in` INTEGER **required**; `quantity_out` INTEGER **required** | Composite PK (`movement_month`, `product_id`); quantities ≥ 0 |
| `agg_annual_stock_in` | `movement_year` INTEGER **required**; `product_id` INTEGER **required**; `quantity_in` INTEGER **required** | Composite PK (`movement_year`, `product_id`); quantity ≥ 0 |

`fact_inventory_snapshot` above represents the latest inventory state per `inventory_id`. If historical snapshots are later needed, add a reliable `snapshot_as_of`/batch key and change its composite primary key; never pretend a latest-only record is a full history.

### 6.2 Naming Convention

- All files, table names, and columns use lowercase `snake_case`.
- Use `dim_` for descriptive reference tables, `fact_` for record-level measurements, and `agg_` for grouped summaries; raw source filenames keep their Stage 1 contract names.
- Preserve source identifiers as `<entity>_id` (e.g., `order_id`, `product_id`). Retain original IDs for traceability; do not invent numeric surrogate keys.
- Dates/times use `_date`, `_at`, or specific names such as `last_updated`; monthly period columns use `YYYY-MM`.
- Output filenames follow the dataset name, such as `fact_order_item.csv`, under an identified transformation run folder.

### 6.3 Source-to-Target Mapping

Every proposed output column has a defined source, transformation, or aggregation. Source IDs remain `INTEGER`, consistent with the Stage 1 documented `INT` fields. All output schemas in Section 6.1 are logical contracts for the Load Stage; values should be verified against the actual Stage 1 schema before code is written.

| Output dataset | Target column(s) | Source / calculation | Rule |
| --- | --- | --- | --- |
| `dim_product` | `product_id` | `products_materials.product_id` | S-07 |
| `dim_product` | `product_name` | `products_materials.product_name`, trimmed; reject blank | C-01, C-02 |
| `dim_product` | `category` | `products_materials.category`; approved category map only | C-01, S-06 |
| `dim_product` | `unit_price` | `products_materials.unit_price`; nonnegative decimal | C-03, S-03 |
| `dim_product` | `reorder_level` | `products_materials.reorder_level`; optional nonnegative integer | S-02 |
| `dim_product` | `product_status` | `products_materials.status`; preserve as product status, not stock balance | C-01 |
| `dim_product` | `updated_at` | `products_materials.updated_at` | S-01 |
| `dim_order` | `order_id` | `orders.order_id` | S-07 |
| `dim_order` | `customer_id` | `orders.customer_id`; reference only (no customer source table in handover) | S-07 |
| `dim_order` | `order_date` | `orders.order_date` | S-01 |
| `dim_order` | `order_status` | `orders.status` through verified approved status mapping | C-07, S-04 |
| `dim_order` | `reported_total_amount` | `orders.total_amount`; source order total, not computed line sum | C-12, S-03 |
| `fact_order_item` | `order_item_id` | `order_items.order_item_id` | S-07 |
| `fact_order_item` | `order_id` | `order_items.order_id`, validated against `dim_order.order_id` | C-06, B-02 |
| `fact_order_item` | `product_id` | `order_items.product_id`, validated against `dim_product.product_id` | C-06, B-03 |
| `fact_order_item` | `order_date`, `order_status` | Lookup through `order_items.order_id = dim_order.order_id` | B-02 |
| `fact_order_item` | `quantity` | `order_items.quantity`, validated positive integer | C-08, S-02 |
| `fact_order_item` | `unit_price` | `order_items.unit_price`, validated decimal | C-09, S-03 |
| `fact_order_item` | `line_amount` | `quantity * unit_price`, decimal with two places | B-01 |
| `fact_inventory_snapshot` | `inventory_id` | `inventory.inventory_id` | S-07 |
| `fact_inventory_snapshot` | `product_id` | `inventory.product_id`, validated against product state | C-06 |
| `fact_inventory_snapshot` | `quantity_on_hand` | `inventory.quantity_on_hand` | C-05, S-02 |
| `fact_inventory_snapshot` | `reorder_level` | `inventory.reorder_level` (no undocumented fallback from product) | S-02 |
| `fact_inventory_snapshot` | `last_updated` | `inventory.last_updated` | S-01 |
| `fact_inventory_snapshot` | `stock_level` | Classify quantity against `inventory.reorder_level`; `UNCLASSIFIED` if required threshold missing | B-10 |
| `fact_stock_movement` | `movement_id` | `stock_movements.movement_id` | S-07 |
| `fact_stock_movement` | `product_id` | `stock_movements.product_id`, validated against product state | C-06 |
| `fact_stock_movement` | `movement_date` | `stock_movements.movement_date` | S-01 |
| `fact_stock_movement` | `movement_month`, `movement_year` | Month/year of `movement_date` using confirmed reporting timezone | B-04 |
| `fact_stock_movement` | `movement_direction` | Verified mapping of `stock_movements.movement_type` | S-05, B-07 |
| `fact_stock_movement` | `quantity` | Normalized **positive magnitude** of source movement quantity after sign convention confirmation | C-10, S-02, B-07 |
| `fact_stock_movement` | `reference_id` | `stock_movements.reference_id` (optional, reference meaning to be verified) | S-07 |
| `agg_monthly_product_demand` | `order_month` | Month of qualified `dim_order.order_date` | B-04, B-05 |
| `agg_monthly_product_demand` | `product_id` | `fact_order_item.product_id` | B-05 |
| `agg_monthly_product_demand` | `quantity_sold` | Sum `fact_order_item.quantity` for eligible orders per month/product | B-05 |
| `agg_monthly_product_demand` | `movement_class` | Monthly quantity sold classified using approved fast/slow threshold | B-11 |
| `agg_monthly_order_sales` | `order_month` | Month of eligible `dim_order.order_date` | B-04, B-06 |
| `agg_monthly_order_sales` | `order_count` | Count distinct eligible `dim_order.order_id` for the month | B-06 |
| `agg_monthly_order_sales` | `sales_amount` | Sum eligible `dim_order.reported_total_amount` **once per order** | B-06 |
| `agg_monthly_product_movement` | `movement_month` | Month of normalized stock movements | B-04, B-08 |
| `agg_monthly_product_movement` | `product_id` | `fact_stock_movement.product_id` | B-08 |
| `agg_monthly_product_movement` | `quantity_in` | Sum movement quantity where verified direction is `IN` | B-08 |
| `agg_monthly_product_movement` | `quantity_out` | Sum movement quantity where verified direction is `OUT` | B-08 |
| `agg_annual_stock_in` | `movement_year` | Year of verified inward stock movement | B-04, B-09 |
| `agg_annual_stock_in` | `product_id` | `fact_stock_movement.product_id` | B-09 |
| `agg_annual_stock_in` | `quantity_in` | Sum `IN` quantity by year and product; **not necessarily purchases** | B-09 |

**Derived data caution:** The extraction contract has no verified purchase-cost, purchase-order, or stock-holding-cost fields. Stage 2 therefore cannot calculate actual procurement spending or ordering-policy financial effects from these five tables alone. Any additional spending/policy measure requires a formally updated source contract and separately defined transformation rule.

### 6.4 Schema Consistency

Validate the input filenames, required columns, key relationships, and convertible data types against the linked Stage 1 schema/manifest **before** transforming. Missing/renamed required columns are **critical failures**: stop the batch, log the schema difference, and request a versioned contract update. Unexpected additional columns may be logged as warnings and ignored only if they do not affect documented rules. Do not automatically change the output schema or silently reinterpret a source field.

## 7. Transformation Validation and Data Quality Checks

| Check name | Target | Purpose | Measurable pass criterion | Severity |
| --- | --- | --- | --- | --- |
| **V-01 Input reconciliation** | Each incremental input table and its processing result | Detect unclassified/dropped incoming records | `input_rows = accepted_insert_or_update_rows + accepted_unchanged_replay_rows + rejected_rows + removed_duplicate_rows`; validate cumulative output counts separately | Critical |
| **V-02 PK uniqueness** | Each `dim_`/`fact_` and composite `agg_` key | Prevent double counting | Duplicate output PK count = 0 | Critical |
| **V-03 Required null check** | Required columns in Section 6 | Prevent incomplete records | Missing required output values = 0 | Critical |
| **V-04 Referential integrity** | All declared fact FKs | Prevent orphans | Unmatched output FKs = 0 | Critical |
| **V-05 Format/type conformance** | Dates, IDs, quantities, monetary fields, statuses | Ensure contract adherence | Invalid converted outputs = 0 | Critical |
| **V-06 Business arithmetic** | `fact_order_item.line_amount` | Verify line calculations | Every amount equals rounded `quantity × unit_price`; no negative values | Critical |
| **V-07 Join cardinality** | Order/product lookups | Prevent row multiplication | Each accepted order item yields exactly one joined fact row | Critical |
| **V-08 Aggregation reconciliation** | Monthly demand/sales and stock summaries | Detect inflated/missing measures | Demand and movement aggregates equal eligible contributing fact quantities; monthly sales sums equal eligible **order-level `orders.total_amount` values counted once per `order_id`** | Critical |
| **V-09 Exclusion audit** | Status filtering, duplicate/quarantined rows | Ensure exclusions are explained | Excluded counts and rule/reason codes fully logged | Critical |
| **V-10 Rejection threshold** | All processed row-level inputs | Control overall quality | `rejected_rows / input_rows <= 1%` (proposed predeclared threshold; see Section 10) | Warning/Review above threshold; any unresolved critical integrity failure stops |
| **V-11 Order-vs-line comparison** | `orders.total_amount` vs associated line sum | Identify possible differences | Record discrepancy count and totals; investigate because discounts, adjustments, fees, and payment behavior are **not fully represented** in this extraction contract | Non-critical warning unless project verifies equality is required |

**Reconciliation details:** For latest-state merging, account for incoming unique inserts, updates that replace existing keyed records, unchanged replays, duplicates, and quarantined input rows separately; do not label a valid update as a second sale. Do not use `input_rows = output_aggregate_rows + rejected_rows` for grouped outputs. Instead reconcile eligible contributing source/fact rows and quantity/amount totals, because many items intentionally produce one aggregate row. For joins, validate the parent key uniqueness and join row cardinality. Filtered-out records are counted by status and reason; cleaning modifications are counted separately as `records_modified`, not rejected.

**Evidence to save:** per-table input/output/duplicate/rejected counts; join unmatched counts; primary-key and null scan results; amount/quantity reconciliation results; per-rule modification counts; a validation report with `PASS`, `WARNING`, or `FAIL`. Real results remain **not yet tested** until implementation runs.

## 8. Transformation Metadata and Log Specification

Each batch creates a transformation-level manifest and run log. Example values below are **format illustrations** and not execution results. The `parent_run_id` format follows the example of `pipeline_run_id` in Stage 1.

| Field | Purpose | Example / format |
| --- | --- | --- |
| `run_id` | Unique transformation attempt | `TRF-20261009-001` |
| `parent_run_id` | Linked approved extraction run | `RUN-20261009-001` (illustrative Stage 1 format) |
| `batch_id` | Stable logical batch identifier | `BATCH-20261009` |
| `extraction_window` | Date/timestamp range copied from approved Stage 1 metadata | Stage 1 extraction-window specification |
| `table_name` | Input/output currently processed | `order_items` |
| `started_at`, `ended_at` | Transformation timestamps | ISO 8601 with offset |
| `status` | Execution state | `STARTED`, `SUCCESS`, `WARNING`, `FAILED`, `HELD` |
| `records_read` | Number of raw rows read from Stage 1 file | Integer |
| `records_output` | Number of unique accepted row-level outputs | Integer |
| `records_rejected` | Quarantined invalid rows | Integer |
| `records_duplicates_removed` | Duplicate extra copies removed with evidence | Integer |
| `records_modified` | Unique retained rows changed by cleaning | Integer |
| `rules_applied` | Counts of modifications/rejections by rule | `{ "C-01": 4, "C-08": 1 }` (illustrative) |
| `records_excluded` | Valid rows excluded from particular metrics | Count by rule/status |
| `validation_results` | Check IDs, counts, outcome | `V-01: PASS` (illustrative) |
| `error_code`, `error_message` | Reason for run failure | Null on successful run |
| `duration_seconds` | Runtime | Nonnegative number |
| `transformation_version` | Exact script/config version | Git commit or tagged version |
| `output_manifest` | Output paths, row counts, schema version, checksums | JSON metadata |

**Proposed storage (not yet created):** `pipeline/logs/transformation/<run_id>/` containing machine-readable `manifest.json`, event log, rule statistics, validation report, and output file checksums. Logs identify data lineage through `parent_run_id` but do not copy all Stage 1 logs. Monitor failures, investigate rejected rows, reproduce a prior run with its rule version, and use a verified manifest for Load handover.

## 9. Log Retention, Rejected Data, and Access

| Item | Proposed policy |
| --- | --- |
| Transformation operational logs | Retain for **at least 30 days** after each run, consistent with the previously proposed minimum Stage 1 log retention; retain longer if an issue remains open |
| Log location | Project-controlled, access-restricted `pipeline/logs/transformation/` (or equivalent approved storage) |
| Quarantine location | `pipeline/quarantine/transformation/<run_id>/` containing rejected row keys/minimum necessary values, rule ID, reason, and batch lineage |
| Quarantine retention | At least 30 days and longer while an incident, audit, correction, or rerun is unresolved |
| Read permissions | Authorized project developers / designated data-quality reviewer only |
| Write permissions | Transformation service account for batch results; authorized developers for controlled remediation |
| Delete permissions | Designated project administrator/owner following documented retention and approval checks |
| Archiving | Archive records still needed for audit or ongoing issue analysis before scheduled deletion |
| Deletion process | Scheduled cleanup by designated administrator only **after** retention period and confirmation of no active investigations or dependencies |
| Security | No passwords, database credentials, or unnecessary customer-identifying details in logs; restrict access and protect storage |

Stage 1 owns extraction logs (source retrieval, extraction completeness, and source-to-staging checks). Stage 2 owns transformation logs (profiling, cleaning, conversion, aggregations, rejected data, and output validation). Keep log ownership and retention distinct even if both use shared infrastructure. Any separately retained audit records require an approved retention policy; no longer audit retention period is claimed here.

**Quarantine fields (minimum):** `run_id`, `parent_run_id`, `batch_id`, `table_name`, `source_record_id`, `rule_id`, `rejection_reason`, `rejected_at`, and a restricted pointer to the input row when needed. Log a minimal data sample, not the entire original record when unnecessary.

## 10. Transformation Acceptance and Handover Rules

**Predeclared proposed rejection limit:** **1%** of row-level input records in a logical batch, counting truly quarantined/rejected records but not rows that were cleaned and retained. This conservative initial threshold is intended to detect significant data-quality issues while permitting isolated recoverable invalid records. The team must approve it **before** observing actual rejection rates; it is not an observed result.

| Condition | Acceptance criteria | Pipeline action | Decision / responsible role |
| --- | --- | --- | --- |
| **Automatic approval** | Stage 1 handover approved; every critical V-check passes; rejected share ≤ 1%; no non-critical warning requiring review; required outputs and checksums complete | Mark `APPROVED`; provide Load handover | Automatic batch rule |
| **Manual review** | Critical checks pass, but a non-critical warning exists **or** rejection share > 1% | Hold handover; determine whether a documented, project-authorized exception can be approved or whether correction/rerun is required | Manual: assigned project data-quality reviewer / project lead |
| **Rejection or failure** | Any critical validation fails, schema is incompatible, unresolved required references remain, or outputs cannot be reliably reproduced | Mark `REJECTED`/`FAILED`; quarantine invalid rows, fix issue, retry same batch without append duplicates | Automatic stop; developer resolves, reviewer approves rerun |
| **Handover to Load** | Batch approved; all output files, row counts, schemas, validation results, checksum metadata and lineage are present | Publish immutable accepted batch folder for Stage 3 | Automatic publication after approved decision |

### 10.1 Handover Package

Provide to Stage 3: approved `dim_`, `fact_`, and `agg_` CSV files from Section 6; output schema/version; `run_id`, `parent_run_id`, batch window; acceptance decision; count and reconciliation summaries; checksums; and pointers to restricted quarantine and validation logs. **Do not load records into the warehouse in Stage 2.**

### 10.2 Validation Summary Template

| Component | Validation result |
| --- | --- |
| Product and order dimensions | NOT YET TESTED |
| Inventory snapshot facts | NOT YET TESTED |
| Order-item facts and monthly demand/sales | NOT YET TESTED |
| Stock-movement facts and movement/stock-in aggregates | NOT YET TESTED |
| Overall transformation acceptance | PENDING IMPLEMENTATION |

Update this template only after an actual run; do not label unexecuted checks `PASS`.

## 11. Common Transformation Problems and Mitigation

| Problem | Possible cause | Impact | Proposed mitigation |
| --- | --- | --- | --- |
| Duplicate rows after batch rerun | Appending an output for the same batch more than once | Repeated item facts and inflated totals | Stable batch IDs; replace/commit batch output atomically; unique source keys; rerun idempotency test |
| Incremental item lacks parent order/product | Parent record unchanged, so absent from current incremental file | Unmatched joins and missing product/month attribution | Join to previously approved reference snapshot; quarantine if still missing; never silently discard |
| Conflicting duplicate records with no timestamp | Source updates yield repeated key without reliable ordering | Incorrect version selected | Quarantine conflicting versions and request review; do not arbitrarily choose last CSV row |
| Incorrect sales totals | Treating pending/cancelled/nonqualifying orders as completed sales | Inflated business performance figures | Verify official source statuses, document eligibility rules, and log excluded records |
| Fast/slow classification based on stock on hand | Using current inventory balance rather than quantity sold | Misleading movement category | Calculate monthly `quantity_sold` from eligible order items; approve classification threshold |
| “Purchases” overstated | Counting all stock-in records as supplier purchases | Incorrect annual procurement report | Report stock-in separately; require verified purchase codes/records before producing a purchased-materials metric |
| Invalid date or timezone assumption | Mixed date strings or timezone-naive timestamps | Incorrect monthly or annual grouping | Enforce S-01; confirm reporting timezone; quarantine unparseable dates |
| Arithmetic/rounding inconsistencies | Floating-point calculation or rounding at inconsistent steps | Line and monthly amount mismatches | Use decimal arithmetic, consistent 2-decimal rounding, and V-06/V-08 checks |
| Aggregated history misses late changes | Historical order/item is updated outside the current reporting month | Stale month totals and forecasts | Recompute affected monthly aggregate keys using approved historical reference state |
| Row multiplication after join | Parent lookup has nonunique `order_id` or `product_id` | Inflated quantities and sales | Deduplicate/validate reference keys before joining; critical join-cardinality check |
| Unexpected extraction schema change | Field renamed/missing or type changed | Transformation script fails or misreads data | Preflight contract/schema version check; log and stop until approved mapping update |
| Large batch delays handover | Data volume increases or expensive aggregation | Stage 3 receives data late | Process by batch/window, cache approved reference state, profile expensive joins, and optimize group operations |
| Unsupported stock movement direction | Source contains an unapproved movement type | Wrong inward/outward totals | Maintain source-approved code mapping; quarantine unknown codes and review with developer |
| Quarantine/log accumulation | No retention cleanup | Storage growth or unwanted sensitive-data exposure | Enforce Section 9 access, retention, archival, and deletion policies |

## Expected Output and Implementation Checklist

The expected Stage 2 deliverable is **documented, traceable, validated, and approved transformed data ready for the Load Stage**. The documentation and proposed output contracts above provide the implementation specification. To claim completion of the implemented transformation, the team must additionally produce real profiling counts, actual batch and rule logs, validated transformed files, and acceptance/handover evidence.

- [ ] Confirm actual Stage 1 handover filenames, paths, run-ID format, and window metadata.
- [ ] Confirm real source data types, permissible order statuses, stock-movement codes, and timestamp timezone.
- [ ] Build profiling and fill in Section 2 measured counts/percentages.
- [ ] Implement and test cleaning, standardization, joins, derived columns, and aggregates.
- [ ] Agree on sales eligibility and fast/slow classification threshold.
- [ ] Verify whether purchases can be distinguished from other stock-in movements; revise extraction scope if necessary.
- [ ] Run V-01–V-11 against actual batches and store evidence.
- [ ] Approve the rejection threshold and run the acceptance decision process.
- [ ] Package approved outputs for Load, without loading in Stage 2.
