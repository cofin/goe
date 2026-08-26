# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

FROM google/cloud-sdk:slim
RUN apt-get update
# Python pre-reqs
RUN apt-get install python3.11 python3.11-venv -y
# Install GOE
ENV OFFLOAD_HOME=/opt/goe/offload
RUN mkdir /opt/goe
COPY goe.tar.gz /opt/goe/
RUN cd /opt/goe && tar xf goe.tar.gz
RUN cd ${OFFLOAD_HOME} && python3.11 -m venv ./.venv
COPY offload.env ${OFFLOAD_HOME}/conf/
RUN . ${OFFLOAD_HOME}/.venv/bin/activate && pip install --root-user-action=ignore --upgrade pip
RUN . ${OFFLOAD_HOME}/.venv/bin/activate && pip install --root-user-action=ignore ${OFFLOAD_HOME}/lib/goe_framework-$(awk '{print $1}' ${OFFLOAD_HOME}/version_build)-py3-none-any.whl
# Entrypoint
COPY goe.sh /opt/goe/
RUN chmod 500 /opt/goe/goe.sh
ENTRYPOINT ["/opt/goe/goe.sh"]
