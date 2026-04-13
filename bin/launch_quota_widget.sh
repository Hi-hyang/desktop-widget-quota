#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_PATH="${USER_WIDGET_CONFIG:-${APP_ROOT}/conf/widget.ini}"
PYTHON_BIN="${USER_WIDGET_PYTHON:-python3}"
APP_SCRIPT="${APP_ROOT}/bin/user_widget_mvp.py"
SHOW_MODE="${USER_WIDGET_SHOW_MODE:-}"

if [[ "${1:-}" == "--show" ]]; then
  SHOW_MODE="1"
fi

if [[ -z "${DISPLAY:-}" ]]; then
  exit 0
fi

SESSION_KEY="${USER}-$(hostname)-$(echo "${DISPLAY}" | tr '/: ' '___')"
LOCK_FILE="/tmp/quota-widget-${SESSION_KEY}.lock"
SHOW_FILE="/tmp/quota-widget-${SESSION_KEY}.show"

read_lock() {
  if [[ -f "${LOCK_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${LOCK_FILE}" || true
  fi
}

write_lock() {
  local pid="$1"
  cat >"${LOCK_FILE}" <<EOF
PID=${pid}
DISPLAY_VALUE=${DISPLAY}
USER_VALUE=${USER}
HOST_VALUE=$(hostname)
EOF
}

clear_lock() {
  rm -f "${LOCK_FILE}"
}

request_show() {
  : >"${SHOW_FILE}"
}

is_pid_alive() {
  local pid="$1"
  [[ -n "${pid:-}" ]] && kill -0 "${pid}" 2>/dev/null
}

pid_matches_app() {
  local pid="$1"
  local cmdline
  cmdline="$(tr '\0' ' ' </proc/${pid}/cmdline 2>/dev/null || true)"
  [[ "${cmdline}" == *"user_widget_mvp.py"* ]]
}

read_lock

if [[ -n "${PID:-}" ]] && is_pid_alive "${PID}" && pid_matches_app "${PID}"; then
  CURRENT_DISPLAY="$(tr '\0' '\n' </proc/${PID}/environ 2>/dev/null | awk -F= '$1=="DISPLAY"{print $2; exit}' || true)"
  if [[ -n "${CURRENT_DISPLAY}" && "${CURRENT_DISPLAY}" == "${DISPLAY}" ]]; then
    if [[ -n "${SHOW_MODE}" ]]; then
      request_show
    fi
    exit 0
  fi
fi

if [[ -n "${PID:-}" ]] && is_pid_alive "${PID}" && pid_matches_app "${PID}"; then
  kill "${PID}" 2>/dev/null || true
  sleep 1
  if is_pid_alive "${PID}"; then
    kill -9 "${PID}" 2>/dev/null || true
  fi
fi

clear_lock

export USER_WIDGET_CONFIG="${CONFIG_PATH}"
export PYTHONUNBUFFERED=1

if [[ -n "${SHOW_MODE}" ]]; then
  export USER_WIDGET_FORCE_SHOW_ON_START=1
fi

nohup "${PYTHON_BIN}" "${APP_SCRIPT}" >/dev/null 2>&1 &
NEW_PID=$!
write_lock "${NEW_PID}"
exit 0
