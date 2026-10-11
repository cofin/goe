# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

FROM google/cloud-sdk:slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV OFFLOAD_HOME=/opt/goe/offload \
    UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_LINK_MODE=copy
RUN mkdir -p /opt/goe
COPY goe.tar.gz /opt/goe/
RUN cd /opt/goe && tar xf goe.tar.gz && rm goe.tar.gz
RUN uv venv --python 3.12 ${OFFLOAD_HOME}/.venv
COPY offload.env ${OFFLOAD_HOME}/conf/
RUN uv pip install --python ${OFFLOAD_HOME}/.venv/bin/python \
    ${OFFLOAD_HOME}/lib/goe_framework-$(awk '{print $1}' ${OFFLOAD_HOME}/version_build)-py3-none-any.whl
COPY goe.sh /opt/goe/
RUN chmod 500 /opt/goe/goe.sh
ENTRYPOINT ["/opt/goe/goe.sh"]
