---
name: goe-schema-drift-and-validation
description: Runbook for detecting frontend/backend schema drift, applying schema synchronization, and validating cross-database data integrity.
---

# GOE Schema Drift and Validation Runbook

## Detecting Schema Drift

1. Read `goe://schemas/{schema_name}/{table_name}/drift` or call `preview_schema_drift` (`GET /api/system/schemas/{schema_name}/{table_name}/drift/`).
2. Inspect the returned `SchemaDiff`:
   - `has_drift`: boolean indicator of frontend vs backend divergence.
   - `added_columns`: columns present in the frontend RDBMS table but absent from the backend table.
   - `missing_columns`: columns present in the backend table but absent from the frontend RDBMS table.
   - `type_mismatches`: columns whose frontend and backend canonical data types diverge.
   - `ddl_statements`: backend `ALTER TABLE ... ADD COLUMN` statements planned for additive columns.
   - `confirmation_challenge`: signed challenge bound to `apply_schema_sync` for `{schema_name}.{table_name}`.

## Applying Schema Synchronization

1. Verify that `added_columns` are expected and that any `type_mismatches` are resolved before mutating the backend table.
2. Call `apply_schema_sync` (`POST /api/orchestration/sync/`) with `owner_table="{schema_name}.{table_name}"`, `execute=true`, and the `confirmation_token` from `preview_schema_drift` (or confirm interactively via MRTR).
3. Re-read `goe://schemas/{schema_name}/{table_name}/drift` to confirm `has_drift` is `false`.

## Cross-Database Validation

1. Call `validate_table` (`POST /api/orchestration/validate/`) with:
   - `validation_type="count"` or `"aggregate"` for fast SQL pushdown verification (passing `scn` for Oracle Flashback snapshot consistency when needed).
   - `validation_type="row"` (with `key_columns`, `where_clause`, and `limit`) for DuckDB row-level diffing (`missing_in_target_count`, `missing_in_source_count`, `mismatched_row_count`).
