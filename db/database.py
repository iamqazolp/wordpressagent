from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker, declarative_base

logger = logging.getLogger(__name__)

# Project root path
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "wordpress_agent.db"

# Create data directory if it doesn't exist
DATA_DIR.mkdir(parents=True, exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

@contextmanager
def session_scope() -> Iterator[Session]:
    """
    Mở một session cho một thao tác nghiệp vụ và luôn đóng khi xong (rollback nếu có lỗi chưa xử lý).
    Không tự commit: crud.* và service tự commit khi ghi. Đọc SessionLocal lúc gọi nên test chỉ cần
    monkeypatch `db.database.SessionLocal` một lần là mọi service dùng DB giả.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _backup_db_file(tag: str = "manual") -> Path | None:
    """Sao lưu DB bằng sqlite3 backup API (an toàn khi app đang chạy). Giữ tối đa 10 bản gần nhất của cùng một `tag`."""
    import sqlite3
    from core.timeutil import now_vn

    if not DB_PATH.exists():
        return None
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"wordpress_agent_{tag}_{now_vn():%Y%m%d_%H%M%S}.db"
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for old in sorted(backup_dir.glob(f"wordpress_agent_{tag}_*.db"), key=lambda p: p.stat().st_mtime)[:-10]:
        old.unlink(missing_ok=True)
    logger.info(f"Đã sao lưu DB: {dest}")
    return dest


def init_db():
    from db.models import Base
    from db.crud import seed_default_templates, migrate_from_json
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    logger.info(f"Initialized database at {DB_PATH}")

    # Versioned schema migrations (xem db/migrations.py). Lỗi migration sẽ dừng app, không bỏ qua im lặng.
    from db.migrations import MIGRATIONS, run_migrations, get_schema_version

    with engine.connect() as conn:
        has_pending = get_schema_version(conn) < max(m[0] for m in MIGRATIONS)
    if has_pending and DB_PATH.exists():
        _backup_db_file("pre-migration")
    run_migrations(engine)
    

    # Seed default templates and migrate data
    db = SessionLocal()
    try:
        seed_default_templates(db)
        json_path = PROJECT_ROOT / "config" / "sites.json"
        if json_path.exists():
            migrate_from_json(db, json_path)
    except Exception as e:
        logger.error(f"Error during db initialization: {e}")
    finally:
        db.close()
