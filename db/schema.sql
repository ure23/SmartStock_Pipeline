-- Initial SmartStock extraction source schema.
-- Keep field names/types aligned with Documentation/Extraction/extraction.md.
-- Non-key columns remain nullable because the source documentation does not
-- define NOT NULL requirements. PostgreSQL DATETIME fields are TIMESTAMP.

CREATE TABLE IF NOT EXISTS products_materials (
    product_id INTEGER PRIMARY KEY,
    product_name VARCHAR(150),
    category VARCHAR(100),
    unit_price DECIMAL(12, 2),
    reorder_level INTEGER,
    status VARCHAR(30),
    updated_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE TABLE IF NOT EXISTS inventory (
    inventory_id INTEGER PRIMARY KEY,
    product_id INTEGER REFERENCES products_materials (product_id),
    quantity_on_hand INTEGER,
    reorder_level INTEGER,
    last_updated TIMESTAMP WITHOUT TIME ZONE
);

CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER,
    order_date DATE,
    status VARCHAR(30),
    total_amount NUMERIC
);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER REFERENCES orders (order_id),
    product_id INTEGER REFERENCES products_materials (product_id),
    quantity NUMERIC,
    unit_price DECIMAL(12, 2)
);

CREATE TABLE IF NOT EXISTS stock_movements (
    movement_id INTEGER PRIMARY KEY,
    product_id INTEGER REFERENCES products_materials (product_id),
    movement_type VARCHAR(30),
    quantity INTEGER,
    movement_date TIMESTAMP WITHOUT TIME ZONE,
    reference_id INTEGER
);

COMMENT ON COLUMN orders.customer_id IS
    'Related identifier; no customers table is defined in the extraction contract.';
COMMENT ON COLUMN stock_movements.reference_id IS
    'Related identifier; the referenced entity is not defined in the extraction contract.';

-- Private pipeline-control metadata. Row contents stay in the canonical source
-- tables; only primary-key strings and SHA-256 digests are retained here.
CREATE TABLE IF NOT EXISTS pipeline_extraction_watermark (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    last_successful_run_id TEXT NOT NULL,
    last_successful_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_extraction_row_state (
    table_name TEXT NOT NULL,
    record_key TEXT NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (table_name, record_key)
);
CREATE TABLE IF NOT EXISTS pipeline_extraction_pending_run (
    run_id TEXT PRIMARY KEY,
    previous_run_id TEXT,
    completed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_extraction_pending_row_state (
    run_id TEXT NOT NULL REFERENCES pipeline_extraction_pending_run(run_id) ON DELETE CASCADE,
    table_name TEXT NOT NULL,
    record_key TEXT NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (run_id, table_name, record_key)
);

COMMENT ON TABLE pipeline_extraction_watermark IS
    'Internal content-snapshot watermark; not part of the five-table CSV contract.';
COMMENT ON TABLE pipeline_extraction_row_state IS
    'Internal primary-key/content-hash state used to emit incremental CSV batches.';
COMMENT ON TABLE pipeline_extraction_pending_run IS
    'A manual-review snapshot awaiting an explicit final acceptance decision.';
COMMENT ON TABLE pipeline_extraction_pending_row_state IS
    'Candidate primary-key/content-hash state committed only if its review batch is approved.';
