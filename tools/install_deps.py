"""
Cài thư viện vào .venv cho install.bat / install.sh — dùng chung logic với launcher (uv, lỗi thì pip).
Chỉ dùng thư viện chuẩn nên chạy được bằng Python hệ thống trước khi có .venv. Mã thoát 1 nếu thất bại.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from launcher import core  # noqa: E402


def main() -> int:
    try:
        core.install(ROOT, lambda line: print(line, flush=True), python=sys.executable)
    except core.LauncherError as e:
        print(f"[X] {e}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
