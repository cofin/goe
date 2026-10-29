-- SPDX-FileCopyrightText: 2016 The GOE Authors
-- SPDX-License-Identifier: Apache-2.0

BEGIN

    UPDATE goe_version
    SET    latest = 'N'
    WHERE  latest = 'Y';

    INSERT INTO goe_version
        (id, version, build, create_time, latest, comments)
    VALUES
        (goe_version_seq.NEXTVAL, '&goe_offload_repo_version', '&goe_build', SYSTIMESTAMP, 'Y',
         NVL('&goe_offload_repo_comments', 'GOE version &goe_offload_repo_version'));

    COMMIT;

END;
/
