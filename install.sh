#!/usr/bin/env bash
# Cài đặt WordPress Agent (macOS / Linux). Chạy một lần: ./install.sh
set -e
cd "$(dirname "$0")"

PY=""
for c in python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "✗ Chưa có Python 3.11 trở lên. Cài từ https://www.python.org/downloads/ rồi chạy lại ./install.sh"
  exit 1
fi
echo "✓ Dùng $($PY --version)"

[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip -q
echo "⏳ Đang cài thư viện (vài phút ở lần đầu)..."
.venv/bin/python -m pip install -r requirements.txt

STATE=$(.venv/bin/python tools/init_env.py || true)
echo
echo "✓ Cài đặt xong."
if [ "$STATE" = "CREATED" ]; then
  echo "👉 Mở file .env và điền GEMINI_API_KEY (bắt buộc), rồi chạy ./run.sh"
else
  echo "👉 Chạy ./run.sh để mở ứng dụng."
fi
