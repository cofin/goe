-- SPDX-FileCopyrightText: 2026 The GOE Authors
-- SPDX-License-Identifier: Apache-2.0

-- name: get_session_events
SELECT event, ROUND(time_waited_micro/1e6,2) FROM v$session_event WHERE sid = SYS_CONTEXT('USERENV','SID');

-- name: agg_validate_sample_column_names
SELECT column_name
FROM  (
       SELECT column_name
       ,      column_id
       ,      MAX(column_id) OVER () AS last_column_id
       ,      ROW_NUMBER() OVER (ORDER BY num_distinct DESC) AS ndv_rank
       FROM   all_tab_cols
       WHERE  owner = :owner
       AND    table_name = :table_name
       AND    hidden_column = 'NO'
      )
WHERE  column_id IN (1, last_column_id)
OR     ndv_rank <= :required_no;

-- name: schema_exists
SELECT 1 FROM dba_users WHERE username = :schema;

-- name: view_exists
SELECT 1 FROM dba_views WHERE owner = :owner AND view_name = :view_name;
