#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_host_service_control
ensure_conda

echo "Newman service status"
echo "Root: ${ROOT_DIR}"
echo "Logs: ${LOG_DIR}"
echo
service_status_line "backend" "${BACKEND_PID_FILE}" "${BACKEND_PORT}" "http://127.0.0.1:${BACKEND_PORT}/healthz"
service_status_line "frontend" "${FRONTEND_PID_FILE}" "${FRONTEND_PORT}" "http://127.0.0.1:${FRONTEND_PORT}"

source "${CONDA_SH}"
conda activate "${ENV_NAME}"

PG_CTL_BIN="$(command -v pg_ctl)"
PG_DATA_DIR="${ROOT_DIR}/backend_data/postgres"
PG_SYSTEM_USER="${NEWMAN_PG_SYSTEM_USER:-newmanpg}"

postgres_has_listener() {
  if command -v ss >/dev/null 2>&1; then
    ss -ltnH 2>/dev/null | awk -v port="${PG_PORT}" '$4 ~ ":" port "$" { found = 1 } END { exit(found ? 0 : 1) }'
    return
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"${PG_PORT}" -sTCP:LISTEN >/dev/null 2>&1
    return
  fi
  return 1
}

postgres_is_running() {
  if [[ -n "${PG_CTL_BIN}" ]]; then
    if [[ "$(id -u)" -eq 0 ]] && getent passwd "${PG_SYSTEM_USER}" >/dev/null 2>&1; then
      chmod o+rx /root /root/anaconda3 /root/anaconda3/envs /root/anaconda3/envs/"${ENV_NAME}" "${ROOT_DIR}" "${ROOT_DIR}/backend_data" 2>/dev/null || true
      chmod 700 "${PG_DATA_DIR}" 2>/dev/null || true
      if su -s /bin/bash "${PG_SYSTEM_USER}" -c "'${PG_CTL_BIN}' -D '${PG_DATA_DIR}' status >/dev/null 2>&1" >/dev/null 2>&1; then
        return 0
      fi
    elif "${PG_CTL_BIN}" -D "${PG_DATA_DIR}" status >/dev/null 2>&1; then
      return 0
    fi
  fi

  postgres_has_listener
}

if postgres_is_running; then
  echo "postgres: running on 127.0.0.1:${PG_PORT}"
else
  echo "postgres: not running"
fi
