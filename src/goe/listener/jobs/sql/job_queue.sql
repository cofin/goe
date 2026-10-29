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
    CANCEL_REQUESTED NUMBER(1)    DEFAULT 0    NOT NULL,
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
    CANCEL_REQUESTED,
    CREATED_AT,
    UPDATED_AT
FROM GOE_LISTENER_JOBS
WHERE STATUS = 'PENDING'
  AND CANCEL_REQUESTED = 0
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

-- name: oracle_reap_expired_to_cancelled
UPDATE GOE_LISTENER_JOBS
SET STATUS           = 'CANCELLED',
    LEASE_EXPIRES_AT = NULL,
    FINISHED_AT      = :now,
    ERROR_MESSAGE    = COALESCE(ERROR_MESSAGE, 'Job cancelled after lease expiration'),
    UPDATED_AT       = :now
WHERE STATUS IN ('CLAIMED', 'RUNNING')
  AND CANCEL_REQUESTED = 1
  AND LEASE_EXPIRES_AT IS NOT NULL
  AND LEASE_EXPIRES_AT <= :now;

-- name: oracle_reap_expired_to_pending
UPDATE GOE_LISTENER_JOBS
SET STATUS           = 'PENDING',
    WORKER_ID        = NULL,
    CLAIMED_AT       = NULL,
    LEASE_EXPIRES_AT = NULL,
    UPDATED_AT       = :now
WHERE STATUS IN ('CLAIMED', 'RUNNING')
  AND CANCEL_REQUESTED = 0
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
  AND CANCEL_REQUESTED = 0
  AND LEASE_EXPIRES_AT IS NOT NULL
  AND LEASE_EXPIRES_AT <= :now
  AND ATTEMPT >= MAX_ATTEMPTS;

-- name: oracle_cancel_pending_or_claimed_job
UPDATE GOE_LISTENER_JOBS
SET STATUS           = 'CANCELLED',
    CANCEL_REQUESTED = 1,
    LEASE_EXPIRES_AT = NULL,
    FINISHED_AT      = :now,
    ERROR_MESSAGE    = COALESCE(:error_message, ERROR_MESSAGE, 'Cancelled by operator'),
    UPDATED_AT       = :now
WHERE EXECUTION_ID = :execution_id
  AND STATUS IN ('PENDING', 'CLAIMED');

-- name: oracle_request_cancel_running_job
UPDATE GOE_LISTENER_JOBS
SET CANCEL_REQUESTED = 1,
    ERROR_MESSAGE    = COALESCE(:error_message, ERROR_MESSAGE),
    UPDATED_AT       = :now
WHERE EXECUTION_ID = :execution_id
  AND STATUS = 'RUNNING';

-- name: oracle_mark_cancelled
UPDATE GOE_LISTENER_JOBS
SET STATUS           = 'CANCELLED',
    CANCEL_REQUESTED = 1,
    LEASE_EXPIRES_AT = NULL,
    FINISHED_AT      = :finished_at,
    ERROR_MESSAGE    = COALESCE(:error_message, ERROR_MESSAGE, 'Cancelled by operator'),
    UPDATED_AT       = :updated_at
WHERE JOB_ID = :job_id
  AND WORKER_ID = :worker_id
  AND STATUS IN ('CLAIMED', 'RUNNING');

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
    CANCEL_REQUESTED,
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
    CANCEL_REQUESTED,
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
    CANCEL_REQUESTED,
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
