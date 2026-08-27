-- SPDX-FileCopyrightText: 2016 The GOE Authors
-- SPDX-License-Identifier: Apache-2.0

set serveroutput on feedback off
begin
  for c in (select username, expiry_date
            from   dba_users
            where  username in ('&goe_db_adm_user','&goe_db_app_user')
            order  by username) loop
    if c.expiry_date is not null then
      dbms_output.put_line('NOTE: ' || c.username || ' password will expire in ' || floor(c.expiry_date - sysdate) || ' days!');
    end if;
  end loop;
end;
/
set feedback on
