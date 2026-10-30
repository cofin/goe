-- SPDX-FileCopyrightText: 2026 The GOE Authors
-- SPDX-License-Identifier: Apache-2.0

define goe_offload_repo_version = '2.4'
define goe_offload_repo_comments = "GOE Listener durable job queue and node endpoints for &goe_offload_repo_version."
define REPO_USER = &goe_db_repo_user

PROMPT Installing GOE repository &goe_offload_repo_version....

-- GOE_LISTENER_JOBS
-- -----------------------------------------------------------------------------------------------
CREATE TABLE &REPO_USER..GOE_LISTENER_JOBS (
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
) TABLESPACE "&goe_repo_tablespace";

CREATE UNIQUE INDEX GOE_LISTENER_JOBS_ACTIVE_TBL_UQ
    ON &REPO_USER..GOE_LISTENER_JOBS (
        CASE WHEN STATUS IN ('PENDING', 'CLAIMED', 'RUNNING') THEN TABLE_KEY END
    )
    TABLESPACE "&goe_repo_tablespace";

CREATE INDEX GOE_LISTENER_JOBS_STATUS_IX
    ON &REPO_USER..GOE_LISTENER_JOBS (STATUS, LEASE_EXPIRES_AT, CREATED_AT)
    TABLESPACE "&goe_repo_tablespace";

-- GOE_LISTENER_ENDPOINTS
-- -----------------------------------------------------------------------------------------------
CREATE TABLE &REPO_USER..GOE_LISTENER_ENDPOINTS (
    ENDPOINT_ID       VARCHAR2(128)            NOT NULL,
    LISTENER_GROUP_ID VARCHAR2(128)            NOT NULL,
    HOST_URL          VARCHAR2(512)            NOT NULL,
    WORKER_ROLE       VARCHAR2(32)             NOT NULL,
    VERSION           VARCHAR2(64)             NOT NULL,
    UPDATED_AT        TIMESTAMP WITH TIME ZONE NOT NULL,
    EXPIRES_AT        TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT GOE_LISTENER_ENDPOINTS_PK PRIMARY KEY (ENDPOINT_ID)
) TABLESPACE "&goe_repo_tablespace";

--------------------------------------------------------------------------------------------------
@@upgrade_offload_repo_version.sql

PROMPT GOE repository &goe_offload_repo_version. installed.

undefine REPO_USER
undefine goe_offload_repo_version
undefine goe_offload_repo_comments
