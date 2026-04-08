#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONDA_PREFIX_DEFAULT="/root/anaconda3"
CONDA_SH="${CONDA_PREFIX_DEFAULT}/etc/profile.d/conda.sh"
ENV_NAME="${NEWMAN_CONDA_ENV:-newman}"
PG_DATA_DIR="${ROOT_DIR}/backend_data/postgres"
PG_SYSTEM_USER="${NEWMAN_PG_SYSTEM_USER:-newmanpg}"

source "${CONDA_SH}"
conda activate "${ENV_NAME}"

PG_CTL_BIN="$(command -v pg_ctl)"

if [[ -z "${PG_CTL_BIN}" ]]; then
  echo "pg_ctl not found in conda env '${ENV_NAME}'. Please recreate the env from environment.yml." >&2
  exit 1
fi

run_as_pg_user() {
  if [[ "$(id -u)" -eq 0 ]]; then
    chmod o+rx /root /root/anaconda3 /root/anaconda3/envs /root/anaconda3/envs/"${ENV_NAME}" "${ROOT_DIR}" "${ROOT_DIR}/backend_data" 2>/dev/null || true
    chmod 700 "${PG_DATA_DIR}" 2>/dev/null || true
    su -s /bin/bash "${PG_SYSTEM_USER}" -c "$1"
  else
    bash -lc "$1"
  fi
}

run_as_pg_user "'${PG_CTL_BIN}' -D '${PG_DATA_DIR}' stop -m fast"
