#!/usr/bin/env bash
set -euo pipefail
workspace_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${workspace_dir}/tools/activate.sh"
cd "${workspace_dir}/projects/hello_world"
idf.py build
