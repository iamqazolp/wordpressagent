import os
import sqlite3
import time
import zipfile

import pytest

from core import backup


def make_db(path, value="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE t (v TEXT)")
    c.execute("INSERT INTO t VALUES (?)", (value,))
    c.commit()
    c.close()


def read_db(path):
    c = sqlite3.connect(path)
    try:
        return [r[0] for r in c.execute("SELECT v FROM t")]
    finally:
        c.close()


@pytest.fixture
def env(tmp_path):
    db = tmp_path / "data" / "app.db"
    make_db(db, "gốc")
    envf = tmp_path / ".env"
    envf.write_text("ENCRYPTION_KEY=abc\n", encoding="utf-8")
    logos = tmp_path / "data" / "logos"
    logos.mkdir()
    (logos / "a.png").write_bytes(b"png")
    return tmp_path, db, envf, logos


def test_auto_backup_creates_then_waits_then_prunes(env):
    tmp, db, *_ = env
    d = tmp / "auto"
    first = backup.auto_backup(d, db)
    assert first and read_db(first) == ["gốc"]
    assert backup.auto_backup(d, db) is None                      # còn mới -> không tạo thêm
    os.utime(first, (time.time() - 30 * 3600,) * 2)               # cũ hơn 20 giờ
    assert backup.auto_backup(d, db) is not None
    for i in range(10):                                           # giữ tối đa `keep`
        for f in d.glob("wordpress_agent_auto_*.db"):
            os.utime(f, (time.time() - 40 * 3600,) * 2)
        backup.auto_backup(d, db, keep=3)
    assert len(list(d.glob("wordpress_agent_auto_*.db"))) <= 3


def test_auto_backup_never_raises(tmp_path):
    assert backup.auto_backup(tmp_path / "x", tmp_path / "missing.db") is None
    bad = tmp_path / "bad.db"
    bad.write_text("not sqlite")
    assert backup.auto_backup(tmp_path / "y", bad) is None


def test_full_backup_roundtrip(env):
    tmp, db, envf, logos = env
    z = backup.create_full_backup(tmp / "out", db, envf, logos)
    assert z.suffix == ".zip"
    with zipfile.ZipFile(z) as zf:
        assert set(zf.namelist()) == {"wordpress_agent.db", "env", "logos/a.png"}
    # hỏng dữ liệu rồi khôi phục
    db.unlink()
    make_db(db, "hỏng")
    envf.write_text("ENCRYPTION_KEY=sai\n", encoding="utf-8")
    (logos / "a.png").unlink()
    safety = backup.restore_full_backup(z, db, envf, logos, safety_dir=tmp / "safe")
    assert read_db(db) == ["gốc"] and envf.read_text(encoding="utf-8") == "ENCRYPTION_KEY=abc\n"
    assert (logos / "a.png").read_bytes() == b"png"
    with zipfile.ZipFile(safety) as zf:                            # dữ liệu 'hỏng' trước đó đã được giữ lại
        assert "wordpress_agent.db" in zf.namelist()


def test_restore_rejects_bad_inputs(env, tmp_path):
    tmp, db, envf, logos = env
    with pytest.raises(backup.BackupError, match="Không tìm thấy"):
        backup.restore_full_backup(tmp / "none.zip", db, envf, logos)
    junk = tmp / "junk.zip"
    junk.write_text("zzz")
    with pytest.raises(backup.BackupError, match="không hợp lệ"):
        backup.restore_full_backup(junk, db, envf, logos)
    nodb = tmp / "nodb.zip"
    with zipfile.ZipFile(nodb, "w") as zf:
        zf.writestr("other.txt", "x")
    with pytest.raises(backup.BackupError, match="không chứa cơ sở dữ liệu"):
        backup.restore_full_backup(nodb, db, envf, logos)
    evil = tmp / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("wordpress_agent.db", "x")
        zf.writestr("../../escape.txt", "x")
    with pytest.raises(backup.BackupError, match="không an toàn"):
        backup.restore_full_backup(evil, db, envf, logos)
    assert read_db(db) == ["gốc"]                                  # các lần từ chối không đụng vào dữ liệu


def test_full_backup_requires_db(tmp_path):
    with pytest.raises(backup.BackupError):
        backup.create_full_backup(tmp_path / "o", tmp_path / "missing.db", tmp_path / ".env", tmp_path / "l")


def test_cli_roundtrip(env, monkeypatch, capsys):
    tmp, db, envf, logos = env
    from tools import backup as cli
    monkeypatch.setattr(backup, "DB_PATH", db)
    monkeypatch.setattr(backup, "ENV_PATH", envf)
    monkeypatch.setattr(backup, "LOGO_DIR", logos)
    assert cli.main(["--to", str(tmp / "cli")]) == 0
    z = next((tmp / "cli").glob("*.zip"))
    assert cli.main(["restore", str(z), "--yes"]) == 0
    assert cli.main(["restore", str(tmp / "no.zip"), "--yes"]) == 1
