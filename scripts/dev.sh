#!/usr/bin/env bash
# Start the NoteKit API reliably.
#
# The editable install of `notekit` has broken repeatedly during development:
# `ModuleNotFoundError: No module named 'notekit'` from a venv that worked
# minutes earlier. The cause was never reproducible on demand (concurrent
# `uv run`, `uv sync --reinstall-package`, and a plain reinstall were all tried
# and none of them broke it), so this script does not try to prevent it. It
# makes it not matter:
#
#   * PYTHONPATH=src means imports work whether or not the .pth survives.
#   * A missing import is repaired rather than reported.
#   * A stale process holding the port is cleared, since uvicorn's own error
#     ("address already in use") sends you looking in the wrong place.
#
# Usage: ./scripts/dev.sh [port]

set -euo pipefail

PORT="${1:-8000}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "→ checking the environment"
# macOS sets UF_HIDDEN on the editable .pth and Python silently skips hidden
# .pth files, which presents as ModuleNotFoundError from a venv that worked
# minutes ago. Clearing the flag is the fix; PYTHONPATH below is the backstop.
PTH=.venv/lib/python3.11/site-packages/_editable_impl_notekit.pth
[ -f "$PTH" ] && chflags nohidden "$PTH" 2>/dev/null || true
# Durable backstop: see scripts/doctor.sh for why a .py rather than a .pth.
"$ROOT/scripts/doctor.sh" >/dev/null 2>&1 || true
if [ ! -d .venv ]; then
  echo "  no .venv, creating"
  uv sync
fi

if ! PYTHONPATH=src .venv/bin/python -c "import notekit" 2>/dev/null; then
  echo "  notekit not importable, rebuilding the environment"
  rm -rf .venv
  uv sync
fi
echo "  ok"

echo "→ freeing port $PORT"
# Both the process actually listening and any orphaned uvicorn from an earlier
# run: the second kind holds nothing but still refuses to start again.
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN | xargs kill 2>/dev/null || true
  sleep 1
fi
pkill -f "uvicorn notekit.api" 2>/dev/null || true
sleep 1
echo "  ok"

echo "→ checking the database"
if ! docker compose ps --status running 2>/dev/null | grep -q notekit-db; then
  echo "  starting postgres"
  docker compose up -d
  sleep 4
fi
echo "  ok"

echo "→ starting the API on :$PORT"
# --reload-dir src keeps .venv churn from restarting the server mid-course.
# PYTHONPATH is the belt to the editable install's braces.
exec env PYTHONPATH=src uv run --no-sync uvicorn notekit.api:app \
  --reload --reload-dir src --port "$PORT"
