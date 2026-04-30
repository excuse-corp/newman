#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_host_service_control
ensure_conda

"${ROOT_DIR}/scripts/dev/start_postgres.sh"

BACKEND_COMMAND=$(cat <<EOF
source "${CONDA_SH}" && \
conda activate "${ENV_NAME}" && \
cd "${ROOT_DIR}" && \
exec uvicorn backend.main:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}"
EOF
)

FRONTEND_COMMAND=$(cat <<EOF
cd "${ROOT_DIR}/frontend" && \
exec node ./node_modules/vite/bin/vite.js --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" --strictPort
EOF
)

start_service \
  "backend" \
  "${BACKEND_PID_FILE}" \
  "${BACKEND_LOG_FILE}" \
  "${BACKEND_PORT}" \
  "${BACKEND_COMMAND}" \
  "http://127.0.0.1:${BACKEND_PORT}/healthz"

start_service \
  "frontend" \
  "${FRONTEND_PID_FILE}" \
  "${FRONTEND_LOG_FILE}" \
  "${FRONTEND_PORT}" \
  "${FRONTEND_COMMAND}" \
  "http://127.0.0.1:${FRONTEND_PORT}"

PRIMARY_IP="$(primary_ipv4_address || true)"

echo
echo "Services are running in the background."
echo "Frontend bind: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
if [[ "${FRONTEND_HOST}" == "0.0.0.0" && -n "${PRIMARY_IP}" ]]; then
  echo "Frontend LAN: http://${PRIMARY_IP}:${FRONTEND_PORT}"
fi
echo "Backend API: http://127.0.0.1:${BACKEND_PORT}"
echo "Backend Docs: http://127.0.0.1:${BACKEND_PORT}/docs"
echo "PostgreSQL: 127.0.0.1:${PG_PORT} (database=newman)"
echo
"${ROOT_DIR}/scripts/dev/status_services.sh"
