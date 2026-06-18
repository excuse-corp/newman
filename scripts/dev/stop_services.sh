#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_host_service_control

stop_service "frontend" "${FRONTEND_PID_FILE}" "${FRONTEND_PORT}"
"${ROOT_DIR}/scripts/dev/stop_feishu_cli_channel.sh" || true
stop_service "backend" "${BACKEND_PID_FILE}" "${BACKEND_PORT}"
"${ROOT_DIR}/scripts/dev/stop_postgres.sh" || true
