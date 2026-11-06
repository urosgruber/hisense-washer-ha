#!/usr/bin/env bash
# Run the washer server on the Mac, for tests before the Home Assistant app.
# The washer must reach this Mac on TCP 443 (DNS override). Data goes to ./data.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  uv venv -p 3.11 .venv
  uv pip install -p .venv/bin/python "paho-mqtt<2" "aiohttp<4"
fi

export WASHER_DATA_DIR="${WASHER_DATA_DIR:-./data}"
export WASHER_DEVICE_BIND="${WASHER_DEVICE_BIND:-0.0.0.0:443}"
export WASHER_WEB_BIND="${WASHER_WEB_BIND:-127.0.0.1:8080}"
exec .venv/bin/python -m washer
