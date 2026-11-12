"""
Cài thư viện vào .venv cho install.bat / install.sh — dùng chung logic với launcher (uv, lỗi thì pip).
Chỉ dùng thư viện chuẩn nên chạy được bằng Python hệ thống trước khi có .venv. Mã thoát 1 nếu thất bại.

  python tools/install_deps.py              # luôn cài
  python tools/install_deps.py --if-needed  # chỉ cài khi chưa có .venv hoặc requirements.txt đã đổi (run.bat / run.sh dùng)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from launcher import core  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--if-needed", action="store_true", help="bỏ qua nếu thư viện đã khớp requirements.txt")
    args = ap.parse_args(argv)
    if args.if_needed and not core.needs_install(ROOT):
        return 0
    if args.if_needed:
        print("Đang cập nhật thư viện cho khớp bản mới (requirements.txt đã đổi)...", flush=True)
    try:
        core.install(ROOT, lambda line: print(line, flush=True), python=sys.executable)
    except core.LauncherError as e:
        print(f"[X] {e}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
