# Client Workbook Adapter (Issue #2 and #4)

This adapter maps only fields present in the imported workbook staging tables. It does not invent missing business facts. Raw staging tables remain unchanged; generated identifier mappings and quarantine row locators are stored in `workbook_import`.

## Source-to-canonical mapping

| Source | Canonical mapping | Rule |
|---|---|---|
| `price_list.product` | `products_materials.product_name` | Preserve the source display string; match by `lower(trim(product))`. |
| `price_list.unit_price` | `products_materials.unit_price` | Direct mapping after checking nonnegative value and the canonical two-decimal contract. |
| Price-list product key | `products_materials.product_id` | Stable generated integer stored in `workbook_import.product_id_map`; source has no product ID. |
| `sales_order_tracker.sales_order_no`, `order_date`, `order_time`, `customer` | `orders.order_id` | Composite natural key was verified unique in the imported snapshot; stable generated integer stored in `workbook_import.order_id_map`. |
| `sales_order_tracker.customer` | `orders.customer_id` | Generated integer keyed by normalized customer name in `workbook_import.customer_id_map`; raw customer text is not written to the CSV. No official customer ID exists in the workbook. |
| `sales_order_tracker.order_date`, `status`, `amount` | `orders.order_date`, `status`, `total_amount` | Direct mapping. Missing status remains NULL; amount is not rounded. |
| `items_sold_tracker` row locator | `order_items.order_item_id` | Stable generated integer keyed by source file name and source row number; source file hash is retained as version provenance. |
| Item order composite | `order_items.order_id` | Exact match to the tracker composite key above. Ambiguous or unmatched joins are quarantined. |
| `items_sold_tracker.product` | `order_items.product_id` | Match by `lower(trim(product))` to the price list; unmatched products are quarantined. |
| `items_sold_tracker.quantity`, `unit_price` | `order_items.quantity`, `unit_price` | Preserve source numeric values; no rounding. |

Workbook fields not present in the source remain NULL: product `category`, `reorder_level`, `status`, and `updated_at`. The adapter does not fabricate inventory snapshots or stock movements; those sources are absent from this workbook.

## Source change/provenance fields

The workbook contains `source_file_sha256` and `source_row_number`, which identify a file version and row locator. Sales rows also contain `order_date` and `order_time`, which describe when an order occurred—not when it was changed. There is no reliable row-level `updated_at`/modified timestamp in these staging tables. The file hash is provenance/version information, not proof of when a business record changed; daily incremental completeness is therefore not claimed.

## Precision and validation

Schema-only profiling found 359 price-list rows, 493 unique order composites, and 1,538 item rows. 1,524 item rows matched both an order and a price-list product; 10 had no matching order, and 4 had no matching product. Those 14 source row locators are quarantined; no raw row values are copied to logs. Two orders have no item rows and remain orders.

The source quantity and order amount fields contain more decimal places than the earlier `INTEGER`/`DECIMAL(12,2)` schema could preserve. The canonical `order_items.quantity` and `orders.total_amount` columns use unconstrained PostgreSQL `NUMERIC` to avoid silent rounding. This is an extraction-stage preservation choice; downstream transformation may apply a separately approved business rounding rule.

## Output and remaining limitations

The Issue #2 and #4 extractors produce their documented CSVs from canonical tables. The inventory extractor remains header-only when the workbook supplies no inventory records. No stock-movement extractor, daily scheduler, incremental watermark, run manifest/log-retention process, or full extraction acceptance gate is implemented by this adapter. Do not mark the full Stage 1 handover approved while these required inputs and controls are absent.
