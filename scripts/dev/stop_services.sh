#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_DIR="${ROOT_DIR}/backend_data/run"
BACKEND_PID_FILE="${RUN_DIR}/backend.pid"
FRONTEND_PID_FILE="${RUN_DIR}/frontend.pid"

stop_process() {
  local name="$1"
  local pid_file="$2"

  if [[ ! -f "${pid_file}" ]]; then
    echo "${name} is not running (missing pid file)"
    return
  fi

  local pid
  pid="$(cat "${pid_file}")"
  if [[ -z "${pid}" ]]; then
    rm -f "${pid_file}"
    echo "${name} pid file was empty"
    return
  fi

  if kill -0 "${pid}" >/dev/null 2>&1; then
    kill "${pid}" >/dev/null 2>&1 || true
    for _ in $(seq 1 20); do
      if ! kill -0 "${pid}" >/dev/null 2>&1; then
        break
      fi
      sleep 0.5
    done
    if kill -0 "${pid}" >/dev/null 2>&1; then
      kill -9 "${pid}" >/dev/null 2>&1 || true
    fi
    echo "Stopped ${name} (pid=${pid})"
  else
    echo "${name} was not running (stale pid=${pid})"
  fi

  rm -f "${pid_file}"
}

stop_process "frontend" "${FRONTEND_PID_FILE}"
stop_process "backend" "${BACKEND_PID_FILE}"
"${ROOT_DIR}/scripts/dev/stop_postgres.sh" || true
