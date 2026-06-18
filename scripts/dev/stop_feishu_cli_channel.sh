#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_host_service_control

if [[ ! -f "${FEISHU_CLI_CHANNEL_PID_FILE}" ]]; then
  echo "feishu-cli-channel is not running"
  exit 0
fi

pid="$(tr -d '[:space:]' <"${FEISHU_CLI_CHANNEL_PID_FILE}")"
if [[ -z "${pid}" ]] || ! is_pid_running "${pid}"; then
  rm -f "${FEISHU_CLI_CHANNEL_PID_FILE}" "${FEISHU_CLI_CHANNEL_READY_FILE}"
  echo "feishu-cli-channel is not running"
  exit 0
fi

kill "${pid}" >/dev/null 2>&1 || true

if wait_for_pid_exit "${pid}"; then
  rm -f "${FEISHU_CLI_CHANNEL_PID_FILE}" "${FEISHU_CLI_CHANNEL_READY_FILE}"
  echo "Stopped feishu-cli-channel (pid=${pid})"
  exit 0
fi

echo "feishu-cli-channel did not stop within ${STOP_TIMEOUT_SECONDS}s; leaving it running to avoid kill -9" >&2
echo "Inspect ${FEISHU_CLI_CHANNEL_LOG_FILE} and stop pid ${pid} manually if needed." >&2
exit 1
