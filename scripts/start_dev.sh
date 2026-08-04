#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8001}"
LOG_DIR="${ROOT_DIR}/logs"
LOG_FILE="${LOG_DIR}/smartreco-dev.log"

mkdir -p "${LOG_DIR}"
cd "${ROOT_DIR}"

echo "Starting SmartReco on http://${HOST}:${PORT}"
echo "Frontend: http://${HOST}:${PORT}/"
echo "Health:   http://${HOST}:${PORT}/health"
echo "Log:      ${LOG_FILE}"

uv run uvicorn app.main:app --reload --host "${HOST}" --port "${PORT}" >>"${LOG_FILE}" 2>&1 &
SERVER_PID=$!

cleanup() {
  echo
  echo "Stopping SmartReco (PID ${SERVER_PID})..."
  kill "${SERVER_PID}" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

for _ in {1..15}; do
  if grep -q "Application startup complete" "${LOG_FILE}" 2>/dev/null; then
    echo "SmartReco started. Tailing logs..."
    tail -f "${LOG_FILE}" &
    TAIL_PID=$!
    wait "${SERVER_PID}" || true
    kill "${TAIL_PID}" 2>/dev/null || true
    exit 0
  fi

  if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    echo "SmartReco failed to start. Recent logs:"
    tail -n 40 "${LOG_FILE}"
    exit 1
  fi
  sleep 1
done

echo "SmartReco did not report startup within 15 seconds. Tailing logs..."
tail -f "${LOG_FILE}" &
TAIL_PID=$!
wait "${SERVER_PID}" || true
kill "${TAIL_PID}" 2>/dev/null || true
