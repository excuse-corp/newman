#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

PG_DATA_DIR="${ROOT_DIR}/backend_data/postgres"
PG_SYSTEM_USER="${NEWMAN_PG_SYSTEM_USER:-newmanpg}"

ensure_host_service_control
ensure_conda

source "${CONDA_SH}"
conda activate "${ENV_NAME}"

PG_CTL_BIN="$(command -v pg_ctl || true)"

if [[ -z "${PG_CTL_BIN}" ]]; then
  echo "pg_ctl not found in conda env '${ENV_NAME}'. Please recreate the env from environment.yml." >&2
  exit 1
fi

run_as_pg_user() {
  if [[ "$(id -u)" -eq 0 ]] && supports_linux_service_user; then
    for path in "${HOME:-}" "$(dirname "${CONDA_SH}")/../.." "${CONDA_PREFIX:-}" "${ROOT_DIR}" "${ROOT_DIR}/backend_data"; do
      [[ -n "${path}" && -e "${path}" ]] && chmod o+rx "${path}" 2>/dev/null || true
    done
    chmod 700 "${PG_DATA_DIR}" 2>/dev/null || true
    su -s /bin/bash "${PG_SYSTEM_USER}" -c "$1"
  else
    bash -lc "$1"
  fi
}

if run_as_pg_user "'${PG_CTL_BIN}' -D '${PG_DATA_DIR}' status >/dev/null 2>&1"; then
  run_as_pg_user "'${PG_CTL_BIN}' -D '${PG_DATA_DIR}' stop -m fast"
  echo "Stopped PostgreSQL"
else
  echo "PostgreSQL is not running"
fi
