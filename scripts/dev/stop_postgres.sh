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

run_as_pg_user() {
  if [[ "$(id -u)" -eq 0 ]]; then
    su -s /bin/bash "${PG_SYSTEM_USER}" -c "$1"
  else
    bash -lc "$1"
  fi
}

run_as_pg_user "pg_ctl -D '${PG_DATA_DIR}' stop -m fast"
