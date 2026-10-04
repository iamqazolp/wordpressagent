#!/usr/bin/env bash
# Sao lưu dữ liệu (CSDL + .env + logo) thành 1 file .zip trong thư mục backups/. Dùng: ./backup.sh [--to THƯ_MỤC]
cd "$(dirname "$0")"
exec .venv/bin/python tools/backup.py "$@"
