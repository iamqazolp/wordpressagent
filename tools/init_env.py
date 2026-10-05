"""
Chuẩn bị file .env lần đầu (được install.sh / install.bat gọi): tạo từ .env.example nếu chưa có và
sinh ENCRYPTION_KEY nếu đang trống. Chạy lại nhiều lần vẫn an toàn — KHÔNG BAO GIỜ đổi khoá đã có
(đổi khoá = không giải mã được mật khẩu website đã lưu).

Mã thoát: 10 nếu vừa tạo .env mới (người dùng cần điền API key), 0 nếu .env đã có. Cũng in 'CREATED'/'EXISTS'.
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _new_key() -> str:
    """Khoá Fernet hợp lệ (32 byte ngẫu nhiên, base64 url-safe) — chỉ dùng thư viện chuẩn để chạy được TRƯỚC khi cài gói."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def ensure_env(root: Path = ROOT) -> str:
    env, example = root / ".env", root / ".env.example"
    created = False
    if not env.exists():
        if example.exists():
            shutil.copyfile(example, env)
        else:
            env.write_text("", encoding="utf-8")
        created = True

    text = env.read_text(encoding="utf-8")
    m = re.search(r"^ENCRYPTION_KEY=(.*)$", text, flags=re.MULTILINE)
    if not m:
        text = text.rstrip("\n") + f"\nENCRYPTION_KEY={_new_key()}\n"
        env.write_text(text, encoding="utf-8")
    elif not m.group(1).strip():
        text = text[: m.start()] + f"ENCRYPTION_KEY={_new_key()}" + text[m.end():]
        env.write_text(text, encoding="utf-8")
    return "CREATED" if created else "EXISTS"


if __name__ == "__main__":
    state = ensure_env()
    print(state)
    sys.exit(10 if state == "CREATED" else 0)
