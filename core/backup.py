"""
core/backup.py — sao lưu / khôi phục dữ liệu (không phụ thuộc giao diện).

Dữ liệu cần giữ gồm 3 thứ, thiếu một là mất mật khẩu website hoặc cấu hình:
  * data/wordpress_agent.db  — website (mật khẩu đã mã hoá), bài viết, template, lịch đăng
  * .env                     — chứa ENCRYPTION_KEY (MẤT KHOÁ = KHÔNG GIẢI MÃ ĐƯỢC MẬT KHẨU WEBSITE) và API key
  * data/logos/              — logo watermark của từng website

- auto_backup(): mỗi lần mở app, nếu chưa có bản tự động nào trong 20 giờ qua thì chụp DB vào data/backups (giữ 7 bản).
- create_full_backup(): gói cả 3 thứ vào một file .zip để cất ở nơi khác (ổ ngoài, cloud riêng tư). File chứa khoá
  và API key nên PHẢI cất kín.
- restore_full_backup(): khôi phục từ file .zip; luôn tạo bản sao lưu an toàn của dữ liệu hiện tại trước khi ghi đè.
"""
from __future__ import annotations

import logging
import sqlite3
import tempfile
import time
import zipfile
from datetime import timedelta
from pathlib import Path

from core.timeutil import now_vn

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "wordpress_agent.db"
ENV_PATH = PROJECT_ROOT / ".env"
LOGO_DIR = DATA_DIR / "logos"
AUTO_DIR = DATA_DIR / "backups"
DEFAULT_FULL_DIR = PROJECT_ROOT / "backups"

AUTO_KEEP = 7
AUTO_MAX_AGE_HOURS = 20
ZIP_DB = "wordpress_agent.db"
ZIP_ENV = "env"            # không đặt tên ".env" để file không bị ẩn khi giải nén thủ công
ZIP_LOGOS = "logos/"


class BackupError(Exception):
    """Lỗi sao lưu/khôi phục có thể nói rõ cho người dùng."""


def snapshot_db(dest: Path, db_path: Path | None = None) -> Path:
    """Chụp DB bằng sqlite3 backup API (an toàn khi app đang chạy)."""
    db_path = db_path or DB_PATH
    if not db_path.exists():
        raise BackupError(f"Không tìm thấy cơ sở dữ liệu: {db_path}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dest


def auto_backup(auto_dir: Path | None = None, db_path: Path | None = None, keep: int = AUTO_KEEP,
                max_age_hours: int = AUTO_MAX_AGE_HOURS) -> Path | None:
    """
    Sao lưu DB tự động tối đa 1 lần/20 giờ. KHÔNG BAO GIỜ raise (không được làm hỏng việc khởi động app).
    Trả đường dẫn bản mới, hoặc None nếu chưa cần/không làm được.
    """
    try:
        auto_dir = auto_dir or AUTO_DIR
        db_path = db_path or DB_PATH
        if not db_path.exists():
            return None
        existing = sorted(auto_dir.glob("wordpress_agent_auto_*.db"), key=lambda p: p.stat().st_mtime)
        if existing:
            age = time.time() - existing[-1].stat().st_mtime   # mtime là epoch thật -> so với time.time()
            if age < timedelta(hours=max_age_hours).total_seconds():
                return None
        dest = snapshot_db(auto_dir / f"wordpress_agent_auto_{now_vn():%Y%m%d_%H%M%S}.db", db_path)
        for old in sorted(auto_dir.glob("wordpress_agent_auto_*.db"), key=lambda p: p.stat().st_mtime)[:-keep]:
            old.unlink(missing_ok=True)
        logger.info(f"Đã sao lưu DB tự động: {dest}")
        return dest
    except Exception:
        logger.exception("Sao lưu tự động thất bại (bỏ qua)")
        return None


def create_full_backup(dest_dir: Path | None = None, db_path: Path | None = None, env_path: Path | None = None,
                       logo_dir: Path | None = None) -> Path:
    """Gói DB + .env + logo vào một file .zip. Trả đường dẫn file. Raise BackupError nếu thiếu DB."""
    db_path = db_path or DB_PATH
    env_path = env_path if env_path is not None else ENV_PATH
    logo_dir = logo_dir if logo_dir is not None else LOGO_DIR
    dest_dir = dest_dir or DEFAULT_FULL_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"wordpress-agent-backup-{now_vn():%Y%m%d-%H%M%S}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        snap = snapshot_db(Path(tmp) / ZIP_DB, db_path)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, ZIP_DB)
            if env_path.exists():
                z.write(env_path, ZIP_ENV)
            if logo_dir.exists():
                for f in sorted(logo_dir.iterdir()):
                    if f.is_file():
                        z.write(f, ZIP_LOGOS + f.name)
    return out


def _safe_member(name: str) -> bool:
    p = Path(name)
    return not p.is_absolute() and ".." not in p.parts


def restore_full_backup(zip_path: Path, db_path: Path | None = None, env_path: Path | None = None,
                        logo_dir: Path | None = None, safety_dir: Path | None = None) -> Path:
    """
    Khôi phục từ file .zip do create_full_backup tạo. Hãy TẮT app trước khi khôi phục.
    Trước khi ghi đè luôn lưu dữ liệu hiện tại vào một .zip an toàn; trả đường dẫn file an toàn đó.
    """
    db_path = db_path or DB_PATH
    env_path = env_path if env_path is not None else ENV_PATH
    logo_dir = logo_dir if logo_dir is not None else LOGO_DIR
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise BackupError(f"Không tìm thấy file sao lưu: {zip_path}")
    try:
        z = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise BackupError("File sao lưu không hợp lệ (không phải file .zip do ứng dụng tạo).")
    with z:
        names = z.namelist()
        if ZIP_DB not in names:
            raise BackupError("File sao lưu không chứa cơ sở dữ liệu — không phải bản sao lưu của ứng dụng này.")
        if not all(_safe_member(n) for n in names):
            raise BackupError("File sao lưu có đường dẫn không an toàn, từ chối khôi phục.")

        safety = None
        if db_path.exists():
            safety = create_full_backup(safety_dir or DEFAULT_FULL_DIR / "truoc-khi-khoi-phuc", db_path, env_path, logo_dir)

        db_path.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
        db_path.write_bytes(z.read(ZIP_DB))
        if ZIP_ENV in names:
            env_path.write_bytes(z.read(ZIP_ENV))
        logos = [n for n in names if n.startswith(ZIP_LOGOS) and not n.endswith("/")]
        if logos:
            logo_dir.mkdir(parents=True, exist_ok=True)
            for n in logos:
                (logo_dir / Path(n).name).write_bytes(z.read(n))
    return safety or zip_path
