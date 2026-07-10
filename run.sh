#!/usr/bin/env bash
#
# run.sh — launch the Non-Profit AI Toolkit prototype (stages 1–2).
#
#   ./run.sh           start the server and open the app in your browser
#   ./run.sh test      start the server, run the simulation harness, then stop
#   ./run.sh test -v   pass flags through to the harness (e.g. --verbose)
#
# The Ollama Cloud key is read from $OLLAMA_API_KEY, or prompted for if unset.
# It lives only in this process's environment — it is never written to disk.
#
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8765}"
URL="http://127.0.0.1:${PORT}"
export PORT

command -v python3 >/dev/null || { echo "python3 not found — install it and re-run." >&2; exit 1; }

# 1. key: from the environment, or prompt for it without echoing
if [[ -z "${OLLAMA_API_KEY:-}" ]]; then
  printf 'ollama cloud api key (hidden, not saved): '
  read -rs OLLAMA_API_KEY || true
  echo
  export OLLAMA_API_KEY
fi
[[ -n "${OLLAMA_API_KEY:-}" ]] || { echo "no key given — get one at https://ollama.com, then re-run." >&2; exit 1; }

# 2. if a previous run still holds the port, stop it
if lsof -ti "tcp:${PORT}" >/dev/null 2>&1; then
  echo "port ${PORT} busy — stopping the old server…"
  lsof -ti "tcp:${PORT}" | xargs kill -9 2>/dev/null || true
  sleep 1
fi

# 3. start the server; always stop it again on exit
echo "starting on ${URL}  (model ${TOOLKIT_MODEL:-glm-5.2})"
python3 server.py &
SERVER_PID=$!
trap 'kill "${SERVER_PID}" 2>/dev/null || true' EXIT

# 4. wait until it answers
for _ in $(seq 1 30); do
  curl -s -o /dev/null "${URL}/" 2>/dev/null && break
  sleep 0.3
done

# 5a. test mode: run the harness and exit with its status
if [[ "${1:-}" == "test" ]]; then
  set +e; python3 tests/simulate.py "${@:2}"; rc=$?; set -e
  exit "${rc}"
fi

# 5b. normal mode: open the browser and stay up until ctrl-c
command -v open >/dev/null && open "${URL}" || echo "open ${URL} in your browser."
echo "ready — press ctrl-c to stop."
wait "${SERVER_PID}"
