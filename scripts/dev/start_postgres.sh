#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONDA_PREFIX_DEFAULT="/root/anaconda3"
CONDA_SH="${CONDA_PREFIX_DEFAULT}/etc/profile.d/conda.sh"
ENV_NAME="${NEWMAN_CONDA_ENV:-newman}"
PG_PORT="${NEWMAN_PG_PORT:-54329}"
PG_DATA_DIR="${ROOT_DIR}/backend_data/postgres"
PG_RUN_DIR="${ROOT_DIR}/backend_data/postgres-run"
PG_LOG_FILE="${PG_RUN_DIR}/postgres.log"
PG_SYSTEM_USER="${NEWMAN_PG_SYSTEM_USER:-newmanpg}"

source "${CONDA_SH}"
conda activate "${ENV_NAME}"

mkdir -p "${PG_DATA_DIR}" "${PG_RUN_DIR}"

run_as_pg_user() {
  if [[ "$(id -u)" -eq 0 ]]; then
    if ! getent passwd "${PG_SYSTEM_USER}" >/dev/null; then
      useradd -m -r -s /bin/bash "${PG_SYSTEM_USER}"
    fi
    chmod o+rx /root /root/anaconda3 /root/anaconda3/envs /root/anaconda3/envs/"${ENV_NAME}" "${ROOT_DIR}" "${ROOT_DIR}/backend_data" "${PG_DATA_DIR}" "${PG_RUN_DIR}"
    chown -R "${PG_SYSTEM_USER}:${PG_SYSTEM_USER}" "${PG_DATA_DIR}" "${PG_RUN_DIR}"
    su -s /bin/bash "${PG_SYSTEM_USER}" -c "$1"
  else
    bash -lc "$1"
  fi
}

run_as_pg_user "test -f '${PG_DATA_DIR}/PG_VERSION' || initdb -D '${PG_DATA_DIR}' -A trust -U postgres"
run_as_pg_user "pg_ctl -D '${PG_DATA_DIR}' -l '${PG_LOG_FILE}' -o '-p ${PG_PORT} -h 127.0.0.1' status >/dev/null 2>&1 || pg_ctl -D '${PG_DATA_DIR}' -l '${PG_LOG_FILE}' -o '-p ${PG_PORT} -h 127.0.0.1' start"
run_as_pg_user "psql -h 127.0.0.1 -p ${PG_PORT} -U postgres -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname = 'newman'\" | grep -q 1 || createdb -h 127.0.0.1 -p ${PG_PORT} -U postgres newman"

echo "PostgreSQL is running on 127.0.0.1:${PG_PORT}, database=newman"
