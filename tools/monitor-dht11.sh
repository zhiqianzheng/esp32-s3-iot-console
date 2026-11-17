#!/usr/bin/env bash
set -euo pipefail
workspace_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${workspace_dir}/tools/activate.sh"
sensor_port="${1:-/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_C4:9E:7E:02:36:10-if00}"
idf.py -C "${workspace_dir}/projects/dht11" -p "${sensor_port}" monitor --no-reset
