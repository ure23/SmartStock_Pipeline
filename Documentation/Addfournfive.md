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
