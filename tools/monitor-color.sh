#!/usr/bin/env bash
set -euo pipefail
workspace_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${workspace_dir}/tools/activate.sh"
color_port="${1:-/dev/ttyACM0}"
idf.py -C "${workspace_dir}/projects/tcs34725" -p "${color_port}" monitor --no-reset
