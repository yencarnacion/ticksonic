#!/usr/bin/env bash
#
# publish.sh – wrap any script in a ttyd web-terminal
# usage: ./publish.sh <script> <symbol> [PORT]
# examples:
#   ./publish.sh s002.sh TSLA         # port 8000 (default)
#   ./publish.sh s300.sh TSLA 8888    # port 8888
# ---------------------------------------------------------------------

set -euo pipefail

# --- parse args -------------------------------------------------------
if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 <script> <symbol> [PORT]" >&2
  exit 1
fi

SCRIPT=$1
SYMBOL=$2
PORT=${3:-8000}

# --- sanity checks ----------------------------------------------------
if [[ ! -x "$SCRIPT" ]]; then
  echo "Error: '$SCRIPT' not found or not executable." >&2
  exit 1
fi

if ! command -v ttyd >/dev/null 2>&1; then
  echo "Error: 'ttyd' is not installed (brew install ttyd)." >&2
  exit 1
fi

# --- launch -----------------------------------------------------------
echo "Serving '$SCRIPT $SYMBOL' on http://localhost:$PORT ..."
exec ttyd -p "$PORT" -- "./$SCRIPT" "$SYMBOL"
