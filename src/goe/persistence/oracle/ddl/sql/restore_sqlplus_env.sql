-- SPDX-FileCopyrightText: 2016 The GOE Authors
-- SPDX-License-Identifier: Apache-2.0

start /tmp/_goe_curr_env.tmp
whenever oserror continue
host /bin/rm /tmp/_goe_curr_env.tmp
