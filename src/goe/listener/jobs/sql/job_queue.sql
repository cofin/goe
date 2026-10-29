-- SPDX-FileCopyrightText: 2026 The GOE Authors
-- SPDX-License-Identifier: Apache-2.0

-- name: oracle_probe_tables
SELECT COUNT(*) AS cnt
FROM ALL_TABLES
WHERE OWNER = UPPER(:repo_user)
  AND TABLE_NAME = 'GOE_LISTENER_JOBS';

-- name: oracle_ddl_jobs_table
CREATE TABLE GOE_LISTENER_JOBS (
    JOB_ID           VARCHAR2(64)               NOT NULL,
    EXECUTION_ID     VARCHAR2(64)               NOT NULL,
    TABLE_KEY        VARCHAR2(260)              NOT NULL,
    STATUS           VARCHAR2(32)               NOT NULL,
    PAYLOAD_JSON     CLOB                       NOT NULL,
    ATTEMPT          NUMBER(10)    DEFAULT 0    NOT NULL,
    MAX_ATTEMPTS     NUMBER(10)    DEFAULT 3    NOT NULL,
    WORKER_ID        VARCHAR2(128),
    CLAIMED_AT       TIMESTAMP WITH TIME ZONE,
    LEASE_EXPIRES_AT TIMESTAMP WITH TIME ZONE,
    STARTED_AT       TIMESTAMP WITH TIME ZONE,
    FINISHED_AT      TIMESTAMP WITH TIME ZONE,
    ERROR_MESSAGE    CLOB,
    CREATED_AT       TIMESTAMP WITH TIME ZONE   NOT NULL,
    UPDATED_AT       TIMESTAMP WITH TIME ZONE   NOT NULL,
    CONSTRAINT GOE_LISTENER_JOBS_PK PRIMARY KEY (JOB_ID),
    CONSTRAINT GOE_LISTENER_JOBS_EXEC_UQ UNIQUE (EXECUTION_ID)
);

-- name: oracle_ddl_active_table_uq
CREATE UNIQUE INDEX GOE_LISTENER_JOBS_ACTIVE_TBL_UQ
ON GOE_LISTENER_JOBS (
    CASE WHEN STATUS IN ('PENDING', 'CLAIMED', 'RUNNING') THEN TABLE_KEY END
);

-- name: oracle_ddl_status_idx
CREATE INDEX GOE_LISTENER_JOBS_STATUS_IX
ON GOE_LISTENER_JOBS (STATUS, LEASE_EXPIRES_AT, CREATED_AT);

-- name: oracle_ddl_endpoints_table
CREATE TABLE GOE_LISTENER_ENDPOINTS (
    ENDPOINT_ID       VARCHAR2(128)            NOT NULL,
    LISTENER_GROUP_ID VARCHAR2(128)            NOT NULL,
    HOST_URL          VARCHAR2(512)            NOT NULL,
    WORKER_ROLE       VARCHAR2(32)             NOT NULL,
    VERSION           VARCHAR2(64)             NOT NULL,
    UPDATED_AT        TIMESTAMP WITH TIME ZONE NOT NULL,
    EXPIRES_AT        TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT GOE_LISTENER_ENDPOINTS_PK PRIMARY KEY (ENDPOINT_ID)
);

-- name: oracle_insert_job
INSERT INTO GOE_LISTENER_JOBS (
    JOB_ID,
    EXECUTION_ID,
    TABLE_KEY,
    STATUS,
    PAYLOAD_JSON,
    ATTEMPT,
    MAX_ATTEMPTS,
    CREATED_AT,
    UPDATED_AT
) VALUES (
    :job_id,
    :execution_id,
    :table_key,
    :status,
    :payload_json,
    :attempt,
    :max_attempts,
    :created_at,
    :updated_at
);

-- name: oracle_claim_pending_jobs
SELECT
    JOB_ID,
    EXECUTION_ID,
    TABLE_KEY,
    STATUS,
    PAYLOAD_JSON,
    ATTEMPT,
    MAX_ATTEMPTS,
    WORKER_ID,
    CLAIMED_AT,
    LEASE_EXPIRES_AT,
    STARTED_AT,
    FINISHED_AT,
    ERROR_MESSAGE,
    CREATED_AT,
    UPDATED_AT
FROM GOE_LISTENER_JOBS
WHERE STATUS = 'PENDING'
ORDER BY CREATED_AT ASC
FOR UPDATE SKIP LOCKED;

-- name: oracle_mark_claimed
UPDATE GOE_LISTENER_JOBS
SET STATUS           = 'CLAIMED',
    ATTEMPT          = ATTEMPT + 1,
    WORKER_ID        = :worker_id,
    CLAIMED_AT       = :claimed_at,
    LEASE_EXPIRES_AT = :lease_expires_at,
    UPDATED_AT       = :updated_at
WHERE JOB_ID = :job_id
  AND STATUS = 'PENDING';

-- name: oracle_mark_running
UPDATE GOE_LISTENER_JOBS
SET STATUS           = 'RUNNING',
    STARTED_AT       = COALESCE(STARTED_AT, :started_at),
    LEASE_EXPIRES_AT = :lease_expires_at,
    UPDATED_AT       = :updated_at
WHERE JOB_ID = :job_id
  AND WORKER_ID = :worker_id
  AND STATUS IN ('CLAIMED', 'RUNNING');

-- name: oracle_renew_lease
UPDATE GOE_LISTENER_JOBS
SET LEASE_EXPIRES_AT = :lease_expires_at,
    UPDATED_AT       = :updated_at
WHERE JOB_ID = :job_id
  AND WORKER_ID = :worker_id
  AND STATUS IN ('CLAIMED', 'RUNNING');

-- name: oracle_mark_terminal
UPDATE GOE_LISTENER_JOBS
SET STATUS           = :status,
    LEASE_EXPIRES_AT = NULL,
    FINISHED_AT      = :finished_at,
    ERROR_MESSAGE    = :error_message,
    UPDATED_AT       = :updated_at
WHERE JOB_ID = :job_id
  AND WORKER_ID = :worker_id
  AND STATUS IN ('CLAIMED', 'RUNNING');

-- name: oracle_reap_expired_to_pending
UPDATE GOE_LISTENER_JOBS
SET STATUS           = 'PENDING',
    WORKER_ID        = NULL,
    CLAIMED_AT       = NULL,
    LEASE_EXPIRES_AT = NULL,
    UPDATED_AT       = :now
WHERE STATUS IN ('CLAIMED', 'RUNNING')
  AND LEASE_EXPIRES_AT IS NOT NULL
  AND LEASE_EXPIRES_AT <= :now
  AND ATTEMPT < MAX_ATTEMPTS;

-- name: oracle_reap_expired_to_dead_letter
UPDATE GOE_LISTENER_JOBS
SET STATUS           = 'DEAD_LETTER',
    LEASE_EXPIRES_AT = NULL,
    FINISHED_AT      = :now,
    ERROR_MESSAGE    = COALESCE(ERROR_MESSAGE, 'Job lease expired and max_attempts exhausted'),
    UPDATED_AT       = :now
WHERE STATUS IN ('CLAIMED', 'RUNNING')
  AND LEASE_EXPIRES_AT IS NOT NULL
  AND LEASE_EXPIRES_AT <= :now
  AND ATTEMPT >= MAX_ATTEMPTS;

-- name: oracle_get_job
SELECT
    JOB_ID,
    EXECUTION_ID,
    TABLE_KEY,
    STATUS,
    PAYLOAD_JSON,
    ATTEMPT,
    MAX_ATTEMPTS,
    WORKER_ID,
    CLAIMED_AT,
    LEASE_EXPIRES_AT,
    STARTED_AT,
    FINISHED_AT,
    ERROR_MESSAGE,
    CREATED_AT,
    UPDATED_AT
FROM GOE_LISTENER_JOBS
WHERE EXECUTION_ID = :execution_id;

-- name: oracle_get_active_job_for_table
SELECT
    JOB_ID,
    EXECUTION_ID,
    TABLE_KEY,
    STATUS,
    PAYLOAD_JSON,
    ATTEMPT,
    MAX_ATTEMPTS,
    WORKER_ID,
    CLAIMED_AT,
    LEASE_EXPIRES_AT,
    STARTED_AT,
    FINISHED_AT,
    ERROR_MESSAGE,
    CREATED_AT,
    UPDATED_AT
FROM GOE_LISTENER_JOBS
WHERE TABLE_KEY = :table_key
  AND STATUS IN ('PENDING', 'CLAIMED', 'RUNNING');

-- name: oracle_list_jobs
SELECT
    JOB_ID,
    EXECUTION_ID,
    TABLE_KEY,
    STATUS,
    PAYLOAD_JSON,
    ATTEMPT,
    MAX_ATTEMPTS,
    WORKER_ID,
    CLAIMED_AT,
    LEASE_EXPIRES_AT,
    STARTED_AT,
    FINISHED_AT,
    ERROR_MESSAGE,
    CREATED_AT,
    UPDATED_AT
FROM GOE_LISTENER_JOBS
WHERE (:status IS NULL OR STATUS = :status)
ORDER BY CREATED_AT DESC;

-- name: oracle_upsert_heartbeat
MERGE INTO GOE_LISTENER_ENDPOINTS dst
USING (
    SELECT
        :endpoint_id       AS ENDPOINT_ID,
        :listener_group_id AS LISTENER_GROUP_ID,
        :host_url          AS HOST_URL,
        :worker_role       AS WORKER_ROLE,
        :version           AS VERSION,
        :updated_at        AS UPDATED_AT,
        :expires_at        AS EXPIRES_AT
    FROM DUAL
) src
ON (dst.ENDPOINT_ID = src.ENDPOINT_ID)
WHEN MATCHED THEN
    UPDATE SET
        dst.LISTENER_GROUP_ID = src.LISTENER_GROUP_ID,
        dst.HOST_URL          = src.HOST_URL,
        dst.WORKER_ROLE       = src.WORKER_ROLE,
        dst.VERSION           = src.VERSION,
        dst.UPDATED_AT        = src.UPDATED_AT,
        dst.EXPIRES_AT        = src.EXPIRES_AT
WHEN NOT MATCHED THEN
    INSERT (
        ENDPOINT_ID,
        LISTENER_GROUP_ID,
        HOST_URL,
        WORKER_ROLE,
        VERSION,
        UPDATED_AT,
        EXPIRES_AT
    ) VALUES (
        src.ENDPOINT_ID,
        src.LISTENER_GROUP_ID,
        src.HOST_URL,
        src.WORKER_ROLE,
        src.VERSION,
        src.UPDATED_AT,
        src.EXPIRES_AT
    );

-- name: oracle_list_active_heartbeats
SELECT
    ENDPOINT_ID,
    LISTENER_GROUP_ID,
    HOST_URL,
    WORKER_ROLE,
    UPDATED_AT,
    EXPIRES_AT,
    VERSION
FROM GOE_LISTENER_ENDPOINTS
WHERE EXPIRES_AT > :now
ORDER BY ENDPOINT_ID ASC;

-- name: sqlite_ddl_jobs_table
CREATE TABLE IF NOT EXISTS goe_listener_jobs (
    job_id           TEXT PRIMARY KEY,
    execution_id     TEXT NOT NULL UNIQUE,
    table_key        TEXT NOT NULL,
    status           TEXT NOT NULL,
    payload_json     TEXT NOT NULL,
    attempt          INTEGER NOT NULL DEFAULT 0,
    max_attempts     INTEGER NOT NULL DEFAULT 3,
    worker_id        TEXT,
    claimed_at       TEXT,
    lease_expires_at TEXT,
    started_at       TEXT,
    finished_at      TEXT,
    error_message    TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- name: sqlite_ddl_active_table_uq
CREATE UNIQUE INDEX IF NOT EXISTS goe_listener_jobs_active_tbl_uq
ON goe_listener_jobs (table_key)
WHERE status IN ('PENDING', 'CLAIMED', 'RUNNING');

-- name: sqlite_ddl_status_idx
CREATE INDEX IF NOT EXISTS goe_listener_jobs_status_ix
ON goe_listener_jobs (status, lease_expires_at, created_at);

-- name: sqlite_ddl_endpoints_table
CREATE TABLE IF NOT EXISTS goe_listener_endpoints (
    endpoint_id       TEXT PRIMARY KEY,
    listener_group_id TEXT NOT NULL,
    host_url          TEXT NOT NULL,
    worker_role       TEXT NOT NULL,
    version           TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    expires_at        TEXT NOT NULL
);

-- name: sqlite_insert_job
INSERT INTO goe_listener_jobs (
    job_id,
    execution_id,
    table_key,
    status,
    payload_json,
    attempt,
    max_attempts,
    created_at,
    updated_at
) VALUES (
    :job_id,
    :execution_id,
    :table_key,
    :status,
    :payload_json,
    :attempt,
    :max_attempts,
    :created_at,
    :updated_at
);

-- name: sqlite_claim_pending_jobs
SELECT
    job_id,
    execution_id,
    table_key,
    status,
    payload_json,
    attempt,
    max_attempts,
    worker_id,
    claimed_at,
    lease_expires_at,
    started_at,
    finished_at,
    error_message,
    created_at,
    updated_at
FROM goe_listener_jobs
WHERE status = 'PENDING'
ORDER BY created_at ASC
LIMIT :limit;

-- name: sqlite_mark_claimed
UPDATE goe_listener_jobs
SET status           = 'CLAIMED',
    attempt          = attempt + 1,
    worker_id        = :worker_id,
    claimed_at       = :claimed_at,
    lease_expires_at = :lease_expires_at,
    updated_at       = :updated_at
WHERE job_id = :job_id
  AND status = 'PENDING';

-- name: sqlite_mark_running
UPDATE goe_listener_jobs
SET status           = 'RUNNING',
    started_at       = COALESCE(started_at, :started_at),
    lease_expires_at = :lease_expires_at,
    updated_at       = :updated_at
WHERE job_id = :job_id
  AND worker_id = :worker_id
  AND status IN ('CLAIMED', 'RUNNING');

-- name: sqlite_renew_lease
UPDATE goe_listener_jobs
SET lease_expires_at = :lease_expires_at,
    updated_at       = :updated_at
WHERE job_id = :job_id
  AND worker_id = :worker_id
  AND status IN ('CLAIMED', 'RUNNING');

-- name: sqlite_mark_terminal
UPDATE goe_listener_jobs
SET status           = :status,
    lease_expires_at = NULL,
    finished_at      = :finished_at,
    error_message    = :error_message,
    updated_at       = :updated_at
WHERE job_id = :job_id
  AND worker_id = :worker_id
  AND status IN ('CLAIMED', 'RUNNING');

-- name: sqlite_reap_expired_to_pending
UPDATE goe_listener_jobs
SET status           = 'PENDING',
    worker_id        = NULL,
    claimed_at       = NULL,
    lease_expires_at = NULL,
    updated_at       = :now
WHERE status IN ('CLAIMED', 'RUNNING')
  AND lease_expires_at IS NOT NULL
  AND lease_expires_at <= :now
  AND attempt < max_attempts;

-- name: sqlite_reap_expired_to_dead_letter
UPDATE goe_listener_jobs
SET status           = 'DEAD_LETTER',
    lease_expires_at = NULL,
    finished_at      = :now,
    error_message    = COALESCE(error_message, 'Job lease expired and max_attempts exhausted'),
    updated_at       = :now
WHERE status IN ('CLAIMED', 'RUNNING')
  AND lease_expires_at IS NOT NULL
  AND lease_expires_at <= :now
  AND attempt >= max_attempts;

-- name: sqlite_get_job
SELECT
    job_id,
    execution_id,
    table_key,
    status,
    payload_json,
    attempt,
    max_attempts,
    worker_id,
    claimed_at,
    lease_expires_at,
    started_at,
    finished_at,
    error_message,
    created_at,
    updated_at
FROM goe_listener_jobs
WHERE execution_id = :execution_id;

-- name: sqlite_get_active_job_for_table
SELECT
    job_id,
    execution_id,
    table_key,
    status,
    payload_json,
    attempt,
    max_attempts,
    worker_id,
    claimed_at,
    lease_expires_at,
    started_at,
    finished_at,
    error_message,
    created_at,
    updated_at
FROM goe_listener_jobs
WHERE table_key = :table_key
  AND status IN ('PENDING', 'CLAIMED', 'RUNNING');

-- name: sqlite_list_jobs
SELECT
    job_id,
    execution_id,
    table_key,
    status,
    payload_json,
    attempt,
    max_attempts,
    worker_id,
    claimed_at,
    lease_expires_at,
    started_at,
    finished_at,
    error_message,
    created_at,
    updated_at
FROM goe_listener_jobs
WHERE (:status IS NULL OR status = :status)
ORDER BY created_at DESC
LIMIT :limit;

-- name: sqlite_upsert_heartbeat
INSERT INTO goe_listener_endpoints (
    endpoint_id,
    listener_group_id,
    host_url,
    worker_role,
    version,
    updated_at,
    expires_at
) VALUES (
    :endpoint_id,
    :listener_group_id,
    :host_url,
    :worker_role,
    :version,
    :updated_at,
    :expires_at
)
ON CONFLICT(endpoint_id) DO UPDATE SET
    listener_group_id = excluded.listener_group_id,
    host_url          = excluded.host_url,
    worker_role       = excluded.worker_role,
    version           = excluded.version,
    updated_at        = excluded.updated_at,
    expires_at        = excluded.expires_at;

-- name: sqlite_list_active_heartbeats
SELECT
    endpoint_id,
    listener_group_id,
    host_url,
    worker_role,
    updated_at,
    expires_at,
    version
FROM goe_listener_endpoints
WHERE expires_at > :now
ORDER BY endpoint_id ASC;
