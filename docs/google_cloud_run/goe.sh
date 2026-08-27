#!/bin/bash

# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

if [[ -z "$1" ]];then
    echo "Usage: $0 offload ..."
    echo "   or: $0 connect"
    exit 1
fi

if [[ "$1" != "connect" && "$1" != "offload" ]];then
    echo "Usage: $0 offload ..."
    echo "   or: $0 connect"
    exit 1
fi

export USER=$(whoami)
. ${OFFLOAD_HOME}/.venv/bin/activate
${OFFLOAD_HOME}/bin/$*
