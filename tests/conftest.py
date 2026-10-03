import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db import database
from db.models import Base


@pytest.fixture
def mem_db(monkeypatch):
    """
    DB SQLite in-memory dùng chung cho test service. Chỉ cần patch `db.database.SessionLocal`
    vì `session_scope()` đọc biến này lúc gọi. Trả về session factory để seed dữ liệu.
    """
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", factory)
    return factory
