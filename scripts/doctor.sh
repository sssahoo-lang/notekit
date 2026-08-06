#!/usr/bin/env bash
# Check the development environment and say what is wrong, in order.
# Repairs the venv; everything else it reports with the fix to run.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
fail=0

check() { printf '  %-34s' "$1"; }
ok()    { echo "ok"; }
bad()   { echo "FAILED — $1"; fail=1; }

echo "NoteKit environment"

check "virtualenv"
[ -d .venv ] && ok || bad "run: uv sync"

check "notekit importable"
if PYTHONPATH=src .venv/bin/python -c "import notekit" 2>/dev/null; then
  ok
else
  echo "broken — rebuilding"
  rm -rf .venv && uv sync >/dev/null 2>&1
  PYTHONPATH=src .venv/bin/python -c "import notekit" 2>/dev/null \
    && echo "  repaired" || bad "uv sync did not fix it"
fi

# scripts/dev.sh sets PYTHONPATH so the server survives without this, but the
# `notekit` console script has no such fallback — repair it rather than warn.
check "editable path present"
if .venv/bin/python -c "import sys; sys.exit(0 if any('NoteKit/src' in p for p in sys.path) else 1)" 2>/dev/null; then
  ok
else
  echo "missing — reinstalling"
  uv sync --reinstall-package notekit >/dev/null 2>&1
  if .venv/bin/python -c "import sys; sys.exit(0 if any('NoteKit/src' in p for p in sys.path) else 1)" 2>/dev/null; then
    echo "  repaired"
  else
    rm -rf .venv && uv sync >/dev/null 2>&1
    .venv/bin/python -c "import notekit" 2>/dev/null \
      && echo "  repaired by rebuilding the venv" || bad "could not repair"
  fi
fi

check "postgres"
docker compose ps --status running 2>/dev/null | grep -q notekit-db \
  && ok || bad "run: docker compose up -d"

check "ANTHROPIC_API_KEY"
if grep -q "^ANTHROPIC_API_KEY=sk-ant-[A-Za-z0-9]" .env 2>/dev/null; then ok
else bad "add a real key to .env"; fi

check "API responding"
curl -s --max-time 4 localhost:8000/api/health >/dev/null 2>&1 \
  && ok || echo "not running — start with: ./scripts/dev.sh"

echo
[ "$fail" -eq 0 ] && echo "All good." || echo "Fix the items marked FAILED above."
exit "$fail"
