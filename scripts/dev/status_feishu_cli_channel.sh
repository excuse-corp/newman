#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

pid_file_value="missing"
state="disabled"
ready="no"
events_count="0"

if is_enabled "${FEISHU_CLI_CHANNEL_ENABLED}"; then
  state="stopped"
fi

if [[ -f "${FEISHU_CLI_CHANNEL_PID_FILE}" ]]; then
  pid_file_value="$(tr -d '[:space:]' <"${FEISHU_CLI_CHANNEL_PID_FILE}")"
  [[ -z "${pid_file_value}" ]] && pid_file_value="empty"
  if is_pid_running "${pid_file_value}"; then
    state="running"
  fi
fi

if [[ -f "${FEISHU_CLI_CHANNEL_READY_FILE}" ]]; then
  ready="$(tr -d '\n' <"${FEISHU_CLI_CHANNEL_READY_FILE}")"
  [[ -z "${ready}" ]] && ready="yes"
fi

if [[ -f "${FEISHU_CLI_CHANNEL_EVENTS_FILE}" ]]; then
  events_count="$(wc -l <"${FEISHU_CLI_CHANNEL_EVENTS_FILE}" | tr -d '[:space:]')"
fi

echo "feishu-cli-channel: state=${state} pid_file=${pid_file_value} ready=${ready} event_key=${FEISHU_CLI_EVENT_KEY} identity=${FEISHU_CLI_IDENTITY} events=${events_count}"
echo "  log=${FEISHU_CLI_CHANNEL_LOG_FILE}"
echo "  events_file=${FEISHU_CLI_CHANNEL_EVENTS_FILE}"
