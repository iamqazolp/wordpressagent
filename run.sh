#!/usr/bin/env bash
# Chạy WordPress Agent (macOS / Linux): ./run.sh
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || ./install.sh || exit 1
export PYTHONUTF8=1
exec .venv/bin/python app.py
