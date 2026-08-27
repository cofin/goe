# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

.DEFAULT_GOAL := install

.PHONY: clean install

LICENCE_LENGTH = 4

TARGET_DIR = ../../target/offload
TARGET_CONF_DIR = $(TARGET_DIR)/conf

install: $(TARGET_CONF_DIR)/oracle-hadoop-offload.env.template \
         $(TARGET_CONF_DIR)/oracle-bigquery-offload.env.template \
         $(TARGET_CONF_DIR)/oracle-snowflake-offload.env.template \
         $(TARGET_CONF_DIR)/oracle-synapse-offload.env.template \
         $(TARGET_CONF_DIR)/teradata-hadoop-offload.env.template \
         $(TARGET_CONF_DIR)/teradata-bigquery-offload.env.template \
         $(TARGET_CONF_DIR)/teradata-snowflake-offload.env.template \
         $(TARGET_CONF_DIR)/teradata-synapse-offload.env.template

$(TARGET_CONF_DIR)/oracle-hadoop-offload.env.template: $(TARGET_CONF_DIR) offload.env.template.common offload.env.template.oracle offload.env.template.hadoop offload.env.template.listener
	cat offload.env.template.common > $(TARGET_CONF_DIR)/oracle-hadoop-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.oracle >> $(TARGET_CONF_DIR)/oracle-hadoop-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.hadoop >> $(TARGET_CONF_DIR)/oracle-hadoop-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.listener >> $(TARGET_CONF_DIR)/oracle-hadoop-offload.env.template

$(TARGET_CONF_DIR)/oracle-bigquery-offload.env.template: $(TARGET_CONF_DIR) offload.env.template.common offload.env.template.oracle offload.env.template.bigquery offload.env.template.listener
	cat offload.env.template.common > $(TARGET_CONF_DIR)/oracle-bigquery-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.oracle >> $(TARGET_CONF_DIR)/oracle-bigquery-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.bigquery >> $(TARGET_CONF_DIR)/oracle-bigquery-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.listener >> $(TARGET_CONF_DIR)/oracle-bigquery-offload.env.template

$(TARGET_CONF_DIR)/oracle-snowflake-offload.env.template: $(TARGET_CONF_DIR) offload.env.template.common offload.env.template.oracle offload.env.template.snowflake offload.env.template.listener
	cat offload.env.template.common > $(TARGET_CONF_DIR)/oracle-snowflake-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.oracle >> $(TARGET_CONF_DIR)/oracle-snowflake-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.snowflake >> $(TARGET_CONF_DIR)/oracle-snowflake-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.listener >> $(TARGET_CONF_DIR)/oracle-snowflake-offload.env.template
	sed -i 's/^OFFLOAD_TRANSPORT_SPARK_SUBMIT_EXECUTABLE=/OFFLOAD_TRANSPORT_SPARK_SUBMIT_EXECUTABLE=spark-submit/' \
			$(TARGET_CONF_DIR)/oracle-snowflake-offload.env.template

$(TARGET_CONF_DIR)/oracle-synapse-offload.env.template: $(TARGET_CONF_DIR) offload.env.template.common offload.env.template.oracle offload.env.template.synapse offload.env.template.listener
	cat offload.env.template.common > $(TARGET_CONF_DIR)/oracle-synapse-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.oracle >> $(TARGET_CONF_DIR)/oracle-synapse-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.synapse >> $(TARGET_CONF_DIR)/oracle-synapse-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.listener >> $(TARGET_CONF_DIR)/oracle-synapse-offload.env.template

$(TARGET_CONF_DIR)/teradata-hadoop-offload.env.template: $(TARGET_CONF_DIR) offload.env.template.common offload.env.template.teradata offload.env.template.hadoop
	cat offload.env.template.common > $(TARGET_CONF_DIR)/teradata-hadoop-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.teradata >> $(TARGET_CONF_DIR)/teradata-hadoop-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.hadoop >> $(TARGET_CONF_DIR)/teradata-hadoop-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.listener >> $(TARGET_CONF_DIR)/teradata-hadoop-offload.env.template

$(TARGET_CONF_DIR)/teradata-bigquery-offload.env.template: $(TARGET_CONF_DIR) offload.env.template.common offload.env.template.teradata offload.env.template.bigquery
	cat offload.env.template.common > $(TARGET_CONF_DIR)/teradata-bigquery-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.teradata >> $(TARGET_CONF_DIR)/teradata-bigquery-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.bigquery >> $(TARGET_CONF_DIR)/teradata-bigquery-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.listener >> $(TARGET_CONF_DIR)/teradata-bigquery-offload.env.template

$(TARGET_CONF_DIR)/teradata-snowflake-offload.env.template: $(TARGET_CONF_DIR) offload.env.template.common offload.env.template.teradata offload.env.template.snowflake
	cat offload.env.template.common > $(TARGET_CONF_DIR)/teradata-snowflake-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.teradata >> $(TARGET_CONF_DIR)/teradata-snowflake-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.snowflake >> $(TARGET_CONF_DIR)/teradata-snowflake-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.listener >> $(TARGET_CONF_DIR)/teradata-snowflake-offload.env.template
	sed -i 's/^OFFLOAD_TRANSPORT_SPARK_SUBMIT_EXECUTABLE=/OFFLOAD_TRANSPORT_SPARK_SUBMIT_EXECUTABLE=spark-submit/' \
			$(TARGET_CONF_DIR)/teradata-snowflake-offload.env.template

$(TARGET_CONF_DIR)/teradata-synapse-offload.env.template: $(TARGET_CONF_DIR) offload.env.template.common offload.env.template.teradata offload.env.template.synapse
	cat offload.env.template.common > $(TARGET_CONF_DIR)/teradata-synapse-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.teradata >> $(TARGET_CONF_DIR)/teradata-synapse-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.synapse >> $(TARGET_CONF_DIR)/teradata-synapse-offload.env.template
	tail -n +$(LICENCE_LENGTH) offload.env.template.listener >> $(TARGET_CONF_DIR)/teradata-synapse-offload.env.template
	sed -i 's/^OFFLOAD_TRANSPORT_SPARK_SUBMIT_EXECUTABLE=/OFFLOAD_TRANSPORT_SPARK_SUBMIT_EXECUTABLE=spark-submit/' \
			$(TARGET_CONF_DIR)/teradata-synapse-offload.env.template

$(TARGET_CONF_DIR):
	mkdir -p $(TARGET_CONF_DIR)

clean:
	rm -f $(TARGET_CONF_DIR)/oracle-hadoop-offload.env.template \
				$(TARGET_CONF_DIR)/oracle-bigquery-offload.env.template \
				$(TARGET_CONF_DIR)/oracle-snowflake-offload.env.template \
				$(TARGET_CONF_DIR)/oracle-synapse-offload.env.template \
				$(TARGET_CONF_DIR)/teradata-hadoop-offload.env.template \
				$(TARGET_CONF_DIR)/teradata-bigquery-offload.env.template \
				$(TARGET_CONF_DIR)/teradata-snowflake-offload.env.template \
				$(TARGET_CONF_DIR)/teradata-synapse-offload.env.template
