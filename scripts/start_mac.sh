#!/usr/bin/env bash
# Start the FinAlly container (macOS/Linux). Idempotent.
set -euo pipefail

IMAGE="finally"
CONTAINER="finally"
VOLUME="finally-data"
PORT="8000"

# Resolve project root (parent of this script's dir)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "Error: .env not found in $ROOT_DIR" >&2
  echo "Copy the template first:  cp .env.example .env  (then add your API key)" >&2
  exit 1
fi

BUILD=false
[[ "${1:-}" == "--build" ]] && BUILD=true

if $BUILD || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building image '$IMAGE'..."
  docker build -t "$IMAGE" .
fi

# Remove any existing container (stopped or running) so this is re-runnable
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  docker rm -f "$CONTAINER" >/dev/null
fi

docker run -d \
  --name "$CONTAINER" \
  -p "${PORT}:8000" \
  -v "${VOLUME}:/app/db" \
  --env-file .env \
  "$IMAGE" >/dev/null

echo "FinAlly is starting at http://localhost:${PORT}"
