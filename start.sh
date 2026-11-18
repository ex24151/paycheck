#!/usr/bin/env bash
# Mac/Linux: run with  bash start.sh
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
[ -f paycheck.db ] || .venv/bin/python -m app.seed
echo "PayCheck running at http://localhost:8000 (Ctrl+C to stop)"
( sleep 2; command -v open >/dev/null && open http://localhost:8000 || xdg-open http://localhost:8000 ) >/dev/null 2>&1 &
.venv/bin/python -m uvicorn app.main:app --port 8000
