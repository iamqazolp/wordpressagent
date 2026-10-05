"""tools/init_env: tạo .env từ mẫu + khoá mã hoá hợp lệ, không bao giờ đổi khoá đã có, chạy được không cần gói ngoài."""
from cryptography.fernet import Fernet

from tools import init_env


def _root(tmp_path, example="GEMINI_API_KEY=\nENCRYPTION_KEY=\nPORT=7860\n"):
    (tmp_path / ".env.example").write_text(example, encoding="utf-8")
    return tmp_path


def test_creates_env_with_valid_fernet_key(tmp_path):
    root = _root(tmp_path)
    assert init_env.ensure_env(root) == "CREATED"
    text = (root / ".env").read_text(encoding="utf-8")
    key = [l for l in text.splitlines() if l.startswith("ENCRYPTION_KEY=")][0].split("=", 1)[1]
    Fernet(key.encode())                      # khoá phải hợp lệ cho Fernet
    assert "GEMINI_API_KEY=" in text and "PORT=7860" in text


def test_never_changes_existing_key_and_is_idempotent(tmp_path):
    root = _root(tmp_path)
    init_env.ensure_env(root)
    first = (root / ".env").read_text(encoding="utf-8")
    assert init_env.ensure_env(root) == "EXISTS"
    assert (root / ".env").read_text(encoding="utf-8") == first


def test_fills_missing_or_empty_key_in_existing_env(tmp_path):
    root = _root(tmp_path)
    (root / ".env").write_text("GEMINI_API_KEY=abc\n", encoding="utf-8")
    assert init_env.ensure_env(root) == "EXISTS"
    assert "ENCRYPTION_KEY=" in (root / ".env").read_text(encoding="utf-8")
    (root / ".env").write_text("ENCRYPTION_KEY=\nX=1\n", encoding="utf-8")
    init_env.ensure_env(root)
    assert len((root / ".env").read_text(encoding="utf-8").split("ENCRYPTION_KEY=")[1].split("\n")[0]) == 44
