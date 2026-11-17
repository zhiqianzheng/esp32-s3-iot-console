#!/usr/bin/env bash
set -euo pipefail
workspace_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${workspace_dir}/host/sensor-dashboard/.venv/bin/python" "${workspace_dir}/host/sensor-dashboard/app.py" "$@"
