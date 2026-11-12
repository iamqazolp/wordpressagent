#!/usr/bin/env bash
# Chạy WordPress Agent (macOS / Linux): ./run.sh
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || ./install.sh || exit 1
export PYTHONUTF8=1
# Bản mới đổi requirements.txt thì cài lại thư viện (giống cửa sổ khởi động), nếu không sẽ lỗi ImportError
.venv/bin/python tools/install_deps.py --if-needed || exit 1
exec .venv/bin/python app.py
