#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_DIR="${ROOT_DIR}/backend_data/run"
BACKEND_PID_FILE="${RUN_DIR}/backend.pid"
FRONTEND_PID_FILE="${RUN_DIR}/frontend.pid"
BACKEND_PORT="${NEWMAN_BACKEND_PORT:-8005}"
FRONTEND_PORT="${NEWMAN_FRONTEND_PORT:-7775}"

is_pid_running() {
  local pid="$1"
  kill -0 "${pid}" >/dev/null 2>&1
}

find_listener_pids_by_port() {
  local port="$1"
  ss -ltnp 2>/dev/null | sed -n "s/.*:${port} .*pid=\\([0-9][0-9]*\\).*/\\1/p" | sort -u
}

wait_for_pid_exit() {
  local pid="$1"
  for _ in $(seq 1 20); do
    if ! is_pid_running "${pid}"; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

kill_pid() {
  local pid="$1"

  if ! is_pid_running "${pid}"; then
    return 0
  fi

  kill "${pid}" >/dev/null 2>&1 || true
  if ! wait_for_pid_exit "${pid}"; then
    kill -9 "${pid}" >/dev/null 2>&1 || true
    wait_for_pid_exit "${pid}" || true
  fi
}

stop_process() {
  local name="$1"
  local pid_file="$2"
  local port="$3"
  local stopped_any="0"

  if [[ -f "${pid_file}" ]]; then
    local pid
    pid="$(cat "${pid_file}")"
    if [[ -z "${pid}" ]]; then
      echo "${name} pid file was empty"
    elif is_pid_running "${pid}"; then
      kill_pid "${pid}"
      echo "Stopped ${name} (pid=${pid})"
      stopped_any="1"
    else
      echo "${name} was not running (stale pid=${pid})"
    fi
    rm -f "${pid_file}"
  fi

  mapfile -t port_pids < <(find_listener_pids_by_port "${port}")
  if [[ "${#port_pids[@]}" -gt 0 ]]; then
    for pid in "${port_pids[@]}"; do
      kill_pid "${pid}"
    done
    echo "Stopped ${name} listener(s) on port ${port}: ${port_pids[*]}"
    stopped_any="1"
  fi

  if [[ "${stopped_any}" == "0" ]]; then
    echo "${name} is not running"
  fi
}

stop_process "frontend" "${FRONTEND_PID_FILE}" "${FRONTEND_PORT}"
stop_process "backend" "${BACKEND_PID_FILE}" "${BACKEND_PORT}"
"${ROOT_DIR}/scripts/dev/stop_postgres.sh" || true
