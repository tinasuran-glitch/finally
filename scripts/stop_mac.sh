#!/usr/bin/env bash
# Stop and remove the FinAlly container (macOS/Linux). Idempotent.
# The named volume is preserved so data persists.
set -euo pipefail

CONTAINER="finally"

if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  docker rm -f "$CONTAINER" >/dev/null
  echo "Stopped and removed container '$CONTAINER' (data volume preserved)."
else
  echo "No container named '$CONTAINER' is running."
fi
