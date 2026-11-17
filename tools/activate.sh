# 在当前终端执行：source tools/activate.sh
_esp32_workspace="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export IDF_TOOLS_PATH="${_esp32_workspace}/tools/espressif"
source "${_esp32_workspace}/sdk/esp-idf/export.sh"
unset _esp32_workspace
