-- create_gluent_app_user.sql
--
-- LICENSE_TEXT
--

@@sql/gen_passwd.sql

prompt Creating &gluent_db_app_user user...

DECLARE
    l_obj_count  NUMBER;
    user_present EXCEPTION;
    PRAGMA EXCEPTION_INIT (user_present, -1920);
BEGIN
    EXECUTE IMMEDIATE 'CREATE USER &gluent_db_app_user IDENTIFIED BY &passwd PROFILE &gluent_db_user_profile';
EXCEPTION
    WHEN user_present THEN
        SELECT COUNT(*)
        INTO   l_obj_count
        FROM   dba_objects
        WHERE  owner = '&gluent_db_app_user';
        IF l_obj_count > 0 THEN
            RAISE_APPLICATION_ERROR(-20000, '&gluent_db_app_user is not an empty schema! &gluent_db_app_user must be empty or not exist.');
        END IF;
END;
/