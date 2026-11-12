"""requirements*.txt/lock được pip đọc theo bảng mã của máy; Windows thường là cp1252/cp1258 -> chỉ cho phép ASCII."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("name", ["requirements.txt", "requirements.lock", "requirements-dev.txt"])
def test_requirements_are_ascii(name):
    data = (ROOT / name).read_bytes()
    bad = [i for i, b in enumerate(data) if b > 127]
    assert not bad, f"{name} có ký tự không phải ASCII (byte {bad[0]}): pip trên Windows có thể lỗi UnicodeDecodeError"


def test_tzdata_on_windows_in_both_files():
    for name in ("requirements.txt", "requirements.lock"):
        lines = (ROOT / name).read_text(encoding="ascii").splitlines()
        assert any(l.startswith("tzdata") and 'sys_platform == "win32"' in l for l in lines), name
