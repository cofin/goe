#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SQL_SOURCE_DIR="${REPO_ROOT}/src/goe/persistence/oracle/ddl"

ORA_SYS_USER="${ORA_SYS_USER:-SYS}"
ORA_SYS_PASS="${ORA_SYS_PASS:-OracleFree23ai}"
ORA_CONN="${ORA_CONN:-localhost:1521/FREEPDB1}"
GOE_USER_PREFIX="${GOE_USER_PREFIX:-GOE}"
GOE_USER_PASS="${GOE_USER_PASS:-goe_ci_pass}"
GOE_TEST_USER="${GOE_TEST_USER:-GOE_TEST}"

OFFLOAD_VERSION="$(sed -rn 's/^version = "([a-zA-Z0-9.-]+)"/\1/p' "${REPO_ROOT}/pyproject.toml" | head -n 1)"
OFFLOAD_VERSION="${OFFLOAD_VERSION:-1.1.0}"
BUILD_HASH="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo "ci")"

WORK_SQL_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_SQL_DIR}"' EXIT

cp -r "${SQL_SOURCE_DIR}/." "${WORK_SQL_DIR}/"
chmod -R u+w "${WORK_SQL_DIR}"

sed -i -e "s/VERSION/${OFFLOAD_VERSION}/g" -e "s/BUILD/${BUILD_HASH}/g" \
  "${WORK_SQL_DIR}/sql/install_env.sql" \
  "${WORK_SQL_DIR}/sql/upgrade_env.sql"
sed -i "s/'%s-SNAPSHOT'/'${OFFLOAD_VERSION} (${BUILD_HASH})'/g" \
  "${WORK_SQL_DIR}"/sql/create_offload*_package_spec.sql
ln -snf . "${WORK_SQL_DIR}/sql/sql"

cat <<EOF > "${WORK_SQL_DIR}/ci_install.sql"
WHENEVER SQLERROR EXIT SQL.SQLCODE
WHENEVER OSERROR EXIT FAILURE
SET VERIFY OFF
SET FEEDBACK ON
SET SERVEROUTPUT ON

DEFINE goe_version = "${OFFLOAD_VERSION}"
DEFINE goe_build = "${BUILD_HASH}"
DEFINE goe_db_user_prefix = "${GOE_USER_PREFIX}"
DEFINE goe_db_user_profile = "DEFAULT"
DEFINE goe_db_adm_user = "${GOE_USER_PREFIX}_ADM"
DEFINE goe_db_app_user = "${GOE_USER_PREFIX}_APP"
DEFINE goe_db_repo_user = "${GOE_USER_PREFIX}_REPO"
DEFINE goe_repo_install = "Y"
DEFINE goe_repo_upgrade = "N"
DEFINE goe_raise_existing_repo_role = "N"
DEFINE goe_repo_tablespace = "USERS"
DEFINE goe_repo_ts_quota = "1G"

@@sql/create_offload_users.sql
@@sql/create_offload_privs.sql
ALTER SESSION SET CURRENT_SCHEMA = &goe_db_adm_user;
@@sql/install_offload_code.sql
@@sql/create_offload_repo.sql
@@sql/upgrade_goe_version.sql

ALTER USER ${GOE_USER_PREFIX}_ADM IDENTIFIED BY "${GOE_USER_PASS}" ACCOUNT UNLOCK;
ALTER USER ${GOE_USER_PREFIX}_APP IDENTIFIED BY "${GOE_USER_PASS}" ACCOUNT UNLOCK;
ALTER USER ${GOE_USER_PREFIX}_REPO IDENTIFIED BY "${GOE_USER_PASS}" ACCOUNT UNLOCK;

DECLARE
  v_count NUMBER;
BEGIN
  FOR u IN (SELECT column_value AS username FROM TABLE(sys.odcivarchar2list(UPPER('${GOE_TEST_USER}'), 'SH_TEST'))) LOOP
    SELECT COUNT(*) INTO v_count FROM dba_users WHERE username = u.username;
    IF v_count = 0 THEN
      EXECUTE IMMEDIATE 'CREATE USER ' || u.username || ' IDENTIFIED BY "${GOE_USER_PASS}" DEFAULT TABLESPACE USERS QUOTA UNLIMITED ON USERS';
    ELSE
      EXECUTE IMMEDIATE 'ALTER USER ' || u.username || ' IDENTIFIED BY "${GOE_USER_PASS}" ACCOUNT UNLOCK QUOTA UNLIMITED ON USERS';
    END IF;
    EXECUTE IMMEDIATE 'GRANT CONNECT, RESOURCE, CREATE VIEW, CREATE MATERIALIZED VIEW, CREATE TABLE, CREATE SEQUENCE, CREATE PROCEDURE, CREATE TYPE, CREATE SYNONYM, FLASHBACK ANY TABLE, SELECT ANY DICTIONARY, UNLIMITED TABLESPACE TO ' || u.username;
    EXECUTE IMMEDIATE 'GRANT SELECT_CATALOG_ROLE TO ' || u.username;
  END LOOP;
END;
/

EXIT
EOF

echo "Bootstrapping GOE schemas (${GOE_USER_PREFIX}_ADM, ${GOE_USER_PREFIX}_APP, ${GOE_USER_PREFIX}_REPO, ${GOE_TEST_USER}, SH_TEST) on ${ORA_CONN}..."
(
  cd "${WORK_SQL_DIR}"
  export SQLPATH="${WORK_SQL_DIR}:${WORK_SQL_DIR}/sql"
  sqlplus -S "${ORA_SYS_USER}/${ORA_SYS_PASS}@//${ORA_CONN} as sysdba" @"${WORK_SQL_DIR}/ci_install.sql"
)
echo "Oracle CI bootstrap complete."
