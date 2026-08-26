-- SPDX-FileCopyrightText: 2016 The GOE Authors
-- SPDX-License-Identifier: Apache-2.0

set serveroutput on

prompt Granting system privileges for &goe_db_repo_user user...
GRANT CREATE SESSION TO &goe_db_repo_user.;
