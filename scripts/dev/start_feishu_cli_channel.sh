#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_host_service_control

if ! is_enabled "${FEISHU_CLI_CHANNEL_ENABLED}"; then
  echo "feishu-cli-channel is disabled (set NEWMAN_FEISHU_CLI_CHANNEL_ENABLED=true to enable)"
  exit 0
fi

if ! command -v "${FEISHU_CLI_BIN}" >/dev/null 2>&1; then
  echo "Feishu CLI binary not found: ${FEISHU_CLI_BIN}" >&2
  echo "Install it with: npx @larksuite/cli@latest install" >&2
  exit 1
fi

mkdir -p "${RUN_DIR}" "${LOG_DIR}" "${FEISHU_CLI_CHANNEL_DATA_DIR}"

if [[ -f "${FEISHU_CLI_CHANNEL_PID_FILE}" ]]; then
  existing_pid="$(tr -d '[:space:]' <"${FEISHU_CLI_CHANNEL_PID_FILE}")"
  if is_pid_running "${existing_pid}"; then
    echo "feishu-cli-channel is already running (pid=${existing_pid})"
    exit 0
  fi
fi

rm -f "${FEISHU_CLI_CHANNEL_PID_FILE}" "${FEISHU_CLI_CHANNEL_READY_FILE}"

{
  echo
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting feishu-cli-channel"
  echo "event_key=${FEISHU_CLI_EVENT_KEY} identity=${FEISHU_CLI_IDENTITY}"
  echo "events_file=${FEISHU_CLI_CHANNEL_EVENTS_FILE}"
} >>"${FEISHU_CLI_CHANNEL_LOG_FILE}"

if ! "${FEISHU_CLI_BIN}" auth status >>"${FEISHU_CLI_CHANNEL_LOG_FILE}" 2>&1; then
  echo "Feishu CLI auth check failed. Run lark-cli config init and lark-cli auth login first." >&2
  tail -n 40 "${FEISHU_CLI_CHANNEL_LOG_FILE}" >&2 || true
  exit 1
fi

(
  child_pid=""
  trap 'if [[ -n "${child_pid}" ]]; then kill "${child_pid}" >/dev/null 2>&1 || true; wait "${child_pid}" >/dev/null 2>&1 || true; fi; exit 0' TERM INT

  "${FEISHU_CLI_BIN}" event consume "${FEISHU_CLI_EVENT_KEY}" --as "${FEISHU_CLI_IDENTITY}" \
    < <(tail -f /dev/null) \
    >>"${FEISHU_CLI_CHANNEL_EVENTS_FILE}" \
    2> >(
      while IFS= read -r line; do
        printf '%s\n' "${line}" >>"${FEISHU_CLI_CHANNEL_LOG_FILE}"
        if [[ "${line}" == "[event] ready event_key=${FEISHU_CLI_EVENT_KEY}"* ]]; then
          date '+%Y-%m-%d %H:%M:%S' >"${FEISHU_CLI_CHANNEL_READY_FILE}"
        fi
      done
    ) &
  child_pid="$!"
  wait "${child_pid}"
) &

managed_pid="$!"
printf '%s\n' "${managed_pid}" >"${FEISHU_CLI_CHANNEL_PID_FILE}"

deadline=$((SECONDS + FEISHU_CLI_READY_TIMEOUT_SECONDS))
while (( SECONDS < deadline )); do
  if ! is_pid_running "${managed_pid}"; then
    echo "feishu-cli-channel exited before becoming ready" >&2
    tail -n 40 "${FEISHU_CLI_CHANNEL_LOG_FILE}" >&2 || true
    rm -f "${FEISHU_CLI_CHANNEL_PID_FILE}"
    exit 1
  fi
  if [[ -f "${FEISHU_CLI_CHANNEL_READY_FILE}" ]]; then
    echo "Started feishu-cli-channel (pid=${managed_pid}), events=${FEISHU_CLI_CHANNEL_EVENTS_FILE}, log=${FEISHU_CLI_CHANNEL_LOG_FILE}"
    exit 0
  fi
  sleep 1
done

echo "feishu-cli-channel started but did not report ready within ${FEISHU_CLI_READY_TIMEOUT_SECONDS}s" >&2
echo "pid=${managed_pid}, log=${FEISHU_CLI_CHANNEL_LOG_FILE}" >&2
tail -n 40 "${FEISHU_CLI_CHANNEL_LOG_FILE}" >&2 || true
exit 1
