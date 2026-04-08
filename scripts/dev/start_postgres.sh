#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONDA_PREFIX_DEFAULT="/root/anaconda3"
CONDA_SH="${CONDA_PREFIX_DEFAULT}/etc/profile.d/conda.sh"
ENV_NAME="${NEWMAN_CONDA_ENV:-newman}"
PG_PORT="${NEWMAN_PG_PORT:-65437}"
PG_DATA_DIR="${ROOT_DIR}/backend_data/postgres"
PG_RUN_DIR="${ROOT_DIR}/backend_data/postgres-run"
PG_LOG_FILE="${PG_RUN_DIR}/postgres.log"
PG_SYSTEM_USER="${NEWMAN_PG_SYSTEM_USER:-newmanpg}"

source "${CONDA_SH}"
conda activate "${ENV_NAME}"

PG_CTL_BIN="$(command -v pg_ctl)"
INITDB_BIN="$(command -v initdb)"
PSQL_BIN="$(command -v psql)"
CREATEDB_BIN="$(command -v createdb)"

if [[ -z "${PG_CTL_BIN}" || -z "${INITDB_BIN}" || -z "${PSQL_BIN}" || -z "${CREATEDB_BIN}" ]]; then
  echo "PostgreSQL binaries not found in conda env '${ENV_NAME}'. Please recreate the env from environment.yml." >&2
  exit 1
fi

mkdir -p "${PG_DATA_DIR}" "${PG_RUN_DIR}"

run_as_pg_user() {
  if [[ "$(id -u)" -eq 0 ]]; then
    if ! getent passwd "${PG_SYSTEM_USER}" >/dev/null; then
      useradd -m -r -s /bin/bash "${PG_SYSTEM_USER}"
    fi
    chmod o+rx /root /root/anaconda3 /root/anaconda3/envs /root/anaconda3/envs/"${ENV_NAME}" "${ROOT_DIR}" "${ROOT_DIR}/backend_data"
    chown -R "${PG_SYSTEM_USER}:${PG_SYSTEM_USER}" "${PG_DATA_DIR}" "${PG_RUN_DIR}"
    chmod 700 "${PG_DATA_DIR}"
    chmod 750 "${PG_RUN_DIR}"
    su -s /bin/bash "${PG_SYSTEM_USER}" -c "$1"
  else
    bash -lc "$1"
  fi
}

current_running_port() {
  local opts_file="${PG_DATA_DIR}/postmaster.opts"
  if [[ ! -f "${opts_file}" ]]; then
    return 1
  fi
  sed -n "s/.* -p \\([0-9][0-9]*\\) .*/\\1/p" "${opts_file}" | head -n 1
}

run_as_pg_user "test -f '${PG_DATA_DIR}/PG_VERSION' || '${INITDB_BIN}' -D '${PG_DATA_DIR}' -A trust -U postgres"

if run_as_pg_user "'${PG_CTL_BIN}' -D '${PG_DATA_DIR}' status >/dev/null 2>&1"; then
  EXISTING_PORT="$(current_running_port || true)"
  if [[ -n "${EXISTING_PORT}" && "${EXISTING_PORT}" != "${PG_PORT}" ]]; then
    echo "PostgreSQL is already running on port ${EXISTING_PORT}; restarting on ${PG_PORT}..."
    run_as_pg_user "'${PG_CTL_BIN}' -D '${PG_DATA_DIR}' stop -m fast"
  fi
fi

run_as_pg_user "'${PG_CTL_BIN}' -D '${PG_DATA_DIR}' -l '${PG_LOG_FILE}' -o '-p ${PG_PORT} -h 127.0.0.1' status >/dev/null 2>&1 || '${PG_CTL_BIN}' -D '${PG_DATA_DIR}' -l '${PG_LOG_FILE}' -o '-p ${PG_PORT} -h 127.0.0.1' start"
run_as_pg_user "'${PSQL_BIN}' -h 127.0.0.1 -p ${PG_PORT} -U postgres -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname = 'newman'\" | grep -q 1 || '${CREATEDB_BIN}' -h 127.0.0.1 -p ${PG_PORT} -U postgres newman"

echo "PostgreSQL is running on 127.0.0.1:${PG_PORT}, database=newman"
