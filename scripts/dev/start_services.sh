#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_DIR="${ROOT_DIR}/backend_data/run"
LOG_DIR="${RUN_DIR}/logs"
BACKEND_PID_FILE="${RUN_DIR}/backend.pid"
FRONTEND_PID_FILE="${RUN_DIR}/frontend.pid"
BACKEND_LOG_FILE="${LOG_DIR}/backend.log"
FRONTEND_LOG_FILE="${LOG_DIR}/frontend.log"
CONDA_PREFIX_DEFAULT="/root/anaconda3"
CONDA_SH="${CONDA_PREFIX_DEFAULT}/etc/profile.d/conda.sh"
ENV_NAME="${NEWMAN_CONDA_ENV:-newman}"
BACKEND_HOST="${NEWMAN_BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${NEWMAN_BACKEND_PORT:-8005}"
FRONTEND_HOST="${NEWMAN_FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${NEWMAN_FRONTEND_PORT:-7775}"

mkdir -p "${RUN_DIR}" "${LOG_DIR}"

ensure_conda() {
  if [[ ! -f "${CONDA_SH}" ]]; then
    echo "conda.sh not found: ${CONDA_SH}" >&2
    exit 1
  fi
}

is_pid_running() {
  local pid="$1"
  kill -0 "${pid}" >/dev/null 2>&1
}

start_process() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  local command="$4"

  if [[ -f "${pid_file}" ]]; then
    local existing_pid
    existing_pid="$(cat "${pid_file}")"
    if [[ -n "${existing_pid}" ]] && is_pid_running "${existing_pid}"; then
      echo "${name} is already running (pid=${existing_pid})"
      return
    fi
    rm -f "${pid_file}"
  fi

  nohup bash -lc "${command}" >>"${log_file}" 2>&1 &
  local pid=$!
  echo "${pid}" >"${pid_file}"
  echo "Started ${name} (pid=${pid}), log=${log_file}"
}

ensure_conda

"${ROOT_DIR}/scripts/dev/start_postgres.sh"

BACKEND_COMMAND=$(cat <<EOF
source "${CONDA_SH}" && \
conda activate "${ENV_NAME}" && \
cd "${ROOT_DIR}" && \
uvicorn backend.main:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}"
EOF
)

FRONTEND_COMMAND=$(cat <<EOF
cd "${ROOT_DIR}/frontend" && \
npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" --strictPort
EOF
)

start_process "backend" "${BACKEND_PID_FILE}" "${BACKEND_LOG_FILE}" "${BACKEND_COMMAND}"
start_process "frontend" "${FRONTEND_PID_FILE}" "${FRONTEND_LOG_FILE}" "${FRONTEND_COMMAND}"

echo
echo "Services are running in the background."
echo "Frontend: http://127.0.0.1:${FRONTEND_PORT}"
echo "Backend API: http://127.0.0.1:${BACKEND_PORT}"
echo "Backend Docs: http://127.0.0.1:${BACKEND_PORT}/docs"
echo "PostgreSQL: 127.0.0.1:${NEWMAN_PG_PORT:-65437} (database=newman)"
