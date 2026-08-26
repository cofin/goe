# SPDX-FileCopyrightText: 2016 The GOE Authors
# SPDX-License-Identifier: Apache-2.0

.PHONY: clean package

OFFLOAD_VERSION=$(shell sed -rn 's/version = "([a-zA-Z0-9.-]+)"/\1/p' ../pyproject.toml)
GOE_PACKAGE=goe_$(OFFLOAD_VERSION).tar.gz
SPARK_PACKAGE=goe_transport_$(OFFLOAD_VERSION).tar.gz

package:
	rm -f ../$(GOE_PACKAGE)
	tar --exclude=".*" -zcf ../$(GOE_PACKAGE) offload
	@echo "Package: $(GOE_PACKAGE)"

package-spark:
	rm -f ../$(SPARK_PACKAGE)
	tar --exclude="spark-*.tgz" -zcf ../$(SPARK_PACKAGE) transport
	@echo "Package: $(SPARK_PACKAGE)"

clean:
	rm -rf offload
	rm -rf transport
