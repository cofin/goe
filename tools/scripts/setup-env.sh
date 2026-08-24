#!/usr/bin/env bash
set -e

# Detect if running on internal Linux (Rodete)
if grep -q "rodete" /etc/os-release 2>/dev/null; then
    echo "Detected internal environment (Rodete)."

    if [ ! -f "uv.toml" ]; then
        echo "Creating uv.toml to force public PyPI index..."
        cat << 'INDEX_EOF' > uv.toml
[[index]]
name = "pypi"
url = "https://pypi.org/simple"
default = true
INDEX_EOF
        echo "uv.toml created."
    else
        echo "uv.toml already exists. Skipping creation."
    fi
else
    echo "Not running on Rodete. Skipping uv.toml creation."
fi
