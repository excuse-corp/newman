#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_DIR="${ROOT_DIR}/backend_data/run"
LOG_DIR="${RUN_DIR}/logs"
BACKEND_PID_FILE="${RUN_DIR}/backend.pid"
FRONTEND_PID_FILE="${RUN_DIR}/frontend.pid"
BACKEND_LOG_FILE="${LOG_DIR}/backend.log"
FRONTEND_LOG_FILE="${LOG_DIR}/frontend.log"

detect_conda_sh() {
  local explicit="${NEWMAN_CONDA_SH:-}"
  if [[ -n "${explicit}" ]]; then
    printf '%s\n' "${explicit}"
    return 0
  fi

  local prefix="${NEWMAN_CONDA_PREFIX:-}"
  if [[ -z "${prefix}" ]] && command -v conda >/dev/null 2>&1; then
    prefix="$(conda info --base 2>/dev/null || true)"
  fi
  if [[ -z "${prefix}" && -n "${CONDA_EXE:-}" ]]; then
    prefix="$(cd "$(dirname "${CONDA_EXE}")/.." >/dev/null 2>&1 && pwd || true)"
  fi

  local candidate
  for candidate in \
    "${prefix}" \
    "${CONDA_PREFIX:-}" \
    "/root/anaconda3" \
    "/root/miniconda3" \
    "${HOME:-}/anaconda3" \
    "${HOME:-}/miniconda3" \
    "${HOME:-}/mambaforge" \
    "${HOME:-}/miniforge3" \
    "/opt/anaconda3" \
    "/opt/miniconda3" \
    "/opt/homebrew/anaconda3" \
    "/opt/homebrew/miniconda3"; do
    if [[ -n "${candidate}" && -f "${candidate}/etc/profile.d/conda.sh" ]]; then
      printf '%s\n' "${candidate}/etc/profile.d/conda.sh"
      return 0
    fi
  done

  printf '%s\n' "${prefix:-/root/anaconda3}/etc/profile.d/conda.sh"
}

CONDA_SH="$(detect_conda_sh)"
ENV_NAME="${NEWMAN_CONDA_ENV:-newman}"
BACKEND_HOST="${NEWMAN_BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${NEWMAN_BACKEND_PORT:-8005}"
FRONTEND_HOST="${NEWMAN_FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${NEWMAN_FRONTEND_PORT:-7775}"
PG_PORT="${NEWMAN_PG_PORT:-65437}"
STARTUP_TIMEOUT_SECONDS="${NEWMAN_STARTUP_TIMEOUT_SECONDS:-30}"
STOP_TIMEOUT_SECONDS="${NEWMAN_STOP_TIMEOUT_SECONDS:-10}"
FEISHU_CLI_CHANNEL_ENABLED="${NEWMAN_FEISHU_CLI_CHANNEL_ENABLED:-false}"
FEISHU_CLI_BIN="${NEWMAN_FEISHU_CLI_BIN:-lark-cli}"
FEISHU_CLI_IDENTITY="${NEWMAN_FEISHU_CLI_IDENTITY:-bot}"
FEISHU_CLI_EVENT_KEY="${NEWMAN_FEISHU_CLI_EVENT_KEY:-im.message.receive_v1}"
FEISHU_CLI_READY_TIMEOUT_SECONDS="${NEWMAN_FEISHU_CLI_READY_TIMEOUT_SECONDS:-20}"
FEISHU_CLI_CHANNEL_PID_FILE="${RUN_DIR}/feishu_cli_channel.pid"
FEISHU_CLI_CHANNEL_READY_FILE="${RUN_DIR}/feishu_cli_channel.ready"
FEISHU_CLI_CHANNEL_LOG_FILE="${LOG_DIR}/feishu_cli_channel.log"
FEISHU_CLI_CHANNEL_DATA_DIR="${ROOT_DIR}/backend_data/channels/feishu_cli"
FEISHU_CLI_CHANNEL_EVENTS_FILE="${FEISHU_CLI_CHANNEL_DATA_DIR}/events.ndjson"

primary_ipv4_address() {
  local ip
  if command -v hostname >/dev/null 2>&1; then
    ip="$(hostname -I 2>/dev/null | awk '{ for (i = 1; i <= NF; i++) if ($i !~ /^127\./) { print $i; exit } }' || true)"
    if [[ -n "${ip}" ]]; then
      printf '%s\n' "${ip}"
      return 0
    fi
  fi

  if command -v ipconfig >/dev/null 2>&1; then
    for iface in en0 en1; do
      ip="$(ipconfig getifaddr "${iface}" 2>/dev/null || true)"
      if [[ -n "${ip}" ]]; then
        printf '%s\n' "${ip}"
        return 0
      fi
    done
  fi

  if command -v ip >/dev/null 2>&1; then
    ip="$(ip route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n 1 || true)"
    if [[ -n "${ip}" ]]; then
      printf '%s\n' "${ip}"
      return 0
    fi
  fi
}

supports_linux_service_user() {
  [[ "$(uname -s 2>/dev/null || true)" == "Linux" ]] && command -v getent >/dev/null 2>&1 && command -v useradd >/dev/null 2>&1
}

ensure_host_service_control() {
  local pid1_cmd
  pid1_cmd="$(ps -p 1 -o cmd= 2>/dev/null || true)"
  if [[ "${pid1_cmd}" == *"codex-linux-sandbox"* || "${pid1_cmd}" == *"bwrap --new-session"* ]]; then
    echo "This script must be run from the host shell, not inside the Codex/bwrap PID sandbox." >&2
    echo "Please run it directly in your terminal, or execute it as an unsandboxed command." >&2
    exit 1
  fi
}

ensure_conda() {
  if [[ ! -f "${CONDA_SH}" ]]; then
    echo "conda.sh not found: ${CONDA_SH}" >&2
    echo "Set NEWMAN_CONDA_SH=/path/to/conda.sh or ensure conda is available on PATH." >&2
    exit 1
  fi
}

is_pid_running() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1
}

is_enabled() {
  case "${1:-}" in
    true|TRUE|True|1|yes|YES|Yes|on|ON|On) return 0 ;;
    *) return 1 ;;
  esac
}

find_listener_pids_by_port() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltnpH 2>/dev/null | sed -n "s/.*:${port} .*pid=\\([0-9][0-9]*\\).*/\\1/p" | sort -u
    return
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null | sort -u
    return
  fi
  return 1
}

wait_for_listener() {
  local port="$1"
  local timeout_seconds="$2"
  local deadline=$((SECONDS + timeout_seconds))
  while (( SECONDS < deadline )); do
    if find_listener_pids_by_port "${port}" | grep -q .; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_http_ok() {
  local url="$1"
  local timeout_seconds="$2"
  if ! command -v curl >/dev/null 2>&1; then
    return 0
  fi
  local deadline=$((SECONDS + timeout_seconds))
  while (( SECONDS < deadline )); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

write_pid_file_from_port() {
  local pid_file="$1"
  local port="$2"
  local pid
  pid="$(find_listener_pids_by_port "${port}" | head -n 1 || true)"
  if [[ -n "${pid}" ]]; then
    printf '%s\n' "${pid}" >"${pid_file}"
    return 0
  fi
  return 1
}

start_service() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  local port="$4"
  local command="$5"
  local ready_url="${6:-}"

  mkdir -p "${RUN_DIR}" "${LOG_DIR}"

  if find_listener_pids_by_port "${port}" | grep -q .; then
    if [[ -n "${ready_url}" ]] && ! wait_for_http_ok "${ready_url}" 2; then
      echo "${name} already has a listener on port ${port}, but the health check failed." >&2
      echo "Run ./scripts/dev/restart_services.sh to replace the unhealthy process." >&2
      return 1
    fi
    write_pid_file_from_port "${pid_file}" "${port}" || true
    echo "${name} is already listening on port ${port}"
    return 0
  fi

  rm -f "${pid_file}"
  {
    echo
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting ${name}"
  } >>"${log_file}"

  nohup bash -lc "${command}" >>"${log_file}" 2>&1 &
  local launcher_pid=$!

  if ! wait_for_listener "${port}" "${STARTUP_TIMEOUT_SECONDS}"; then
    echo "Failed to start ${name}: no listener appeared on port ${port}" >&2
    tail -n 40 "${log_file}" >&2 || true
    return 1
  fi

  if [[ -n "${ready_url}" ]] && ! wait_for_http_ok "${ready_url}" "${STARTUP_TIMEOUT_SECONDS}"; then
    echo "Failed to verify ${name}: ${ready_url} did not become healthy" >&2
    tail -n 40 "${log_file}" >&2 || true
    return 1
  fi

  if ! write_pid_file_from_port "${pid_file}" "${port}"; then
    printf '%s\n' "${launcher_pid}" >"${pid_file}"
  fi

  echo "Started ${name} on port ${port} (pid=$(cat "${pid_file}")), log=${log_file}"
}

wait_for_pid_exit() {
  local pid="$1"
  local deadline=$((SECONDS + STOP_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if ! is_pid_running "${pid}"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

kill_pid_gracefully() {
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

stop_service() {
  local name="$1"
  local pid_file="$2"
  local port="$3"

  local targets=""
  local pid

  if [[ -f "${pid_file}" ]]; then
    pid="$(tr -d '[:space:]' <"${pid_file}")"
    if [[ -n "${pid}" ]]; then
      targets="${targets}${pid}"$'\n'
    fi
  fi

  while IFS= read -r pid; do
    [[ -n "${pid}" ]] && targets="${targets}${pid}"$'\n'
  done < <(find_listener_pids_by_port "${port}" || true)

  targets="$(printf '%s' "${targets}" | sed '/^[[:space:]]*$/d' | sort -u)"

  if [[ -z "${targets}" ]]; then
    rm -f "${pid_file}"
    echo "${name} is not running"
    return 0
  fi

  while IFS= read -r pid; do
    [[ -z "${pid}" ]] && continue
    kill_pid_gracefully "${pid}"
  done <<<"${targets}"
  rm -f "${pid_file}"
  echo "Stopped ${name} on port ${port}: $(printf '%s' "${targets}" | paste -sd ',' -)"
}

service_status_line() {
  local name="$1"
  local pid_file="$2"
  local port="$3"
  local ready_url="${4:-}"

  local pid_file_value="missing"
  local listener_pids="none"
  local health="n/a"

  if [[ -f "${pid_file}" ]]; then
    pid_file_value="$(tr -d '[:space:]' <"${pid_file}")"
    [[ -z "${pid_file_value}" ]] && pid_file_value="empty"
  fi

  listener_pids="$(find_listener_pids_by_port "${port}" | paste -sd ',' - || true)"
  [[ -z "${listener_pids}" ]] && listener_pids="none"

  if [[ -n "${ready_url}" ]] && command -v curl >/dev/null 2>&1; then
    if curl -fsS "${ready_url}" >/dev/null 2>&1; then
      health="ok"
    else
      health="down"
    fi
  fi

  echo "${name}: port=${port} pid_file=${pid_file_value} listeners=${listener_pids} health=${health}"
}
