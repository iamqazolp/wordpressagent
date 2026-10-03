import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine, text

from db.migrations import (
    MIGRATIONS,
    add_column_if_missing,
    column_names,
    get_schema_version,
    run_migrations,
)


@pytest.fixture
def engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'test.db'}")


def _make_legacy_schema(engine):
    """Schema cũ: thiếu các cột được thêm ở Phase 2/3.1."""
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE sites (id INTEGER PRIMARY KEY, name VARCHAR(100))"))
        conn.execute(text("CREATE TABLE post_history (id INTEGER PRIMARY KEY, title VARCHAR(500))"))
        conn.execute(text("INSERT INTO sites (id, name) VALUES (1, 'keep-me')"))


def test_legacy_db_gets_upgraded_and_keeps_data(engine):
    _make_legacy_schema(engine)
    version = run_migrations(engine)

    assert version == max(m[0] for m in MIGRATIONS)
    with engine.connect() as conn:
        assert {"watermark_path", "watermark_position", "watermark_opacity"} <= column_names(conn, "sites")
        assert {"short_description", "regular_price", "sale_price", "image_paths_json"} <= column_names(conn, "post_history")
        assert conn.execute(text("SELECT name FROM sites WHERE id=1")).scalar() == "keep-me"


def test_run_twice_is_idempotent(engine):
    _make_legacy_schema(engine)
    v1 = run_migrations(engine)
    v2 = run_migrations(engine)
    assert v1 == v2
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT COUNT(*) FROM schema_version")).scalar()
    assert rows == len(MIGRATIONS)


def test_fresh_db_without_tables_is_noop(engine):
    # Bảng chưa có (create_all chưa chạy) -> không lỗi
    assert run_migrations(engine) == max(m[0] for m in MIGRATIONS)


def test_failed_migration_rolls_back_and_stops(engine):
    calls = []

    def ok(conn):
        calls.append("ok")
        conn.execute(text("CREATE TABLE t1 (id INTEGER)"))

    def boom(conn):
        conn.execute(text("CREATE TABLE t2 (id INTEGER)"))
        raise RuntimeError("fail")

    def never(conn):
        calls.append("never")

    with pytest.raises(RuntimeError):
        run_migrations(engine, [(1, "ok", ok), (2, "boom", boom), (3, "never", never)])

    assert calls == ["ok"]
    with engine.connect() as conn:
        assert get_schema_version(conn) == 1
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert "t1" in tables
    assert "t2" not in tables  # đã rollback


def test_duplicate_versions_rejected(engine):
    with pytest.raises(ValueError):
        run_migrations(engine, [(1, "a", lambda c: None), (1, "b", lambda c: None)])


def test_add_column_if_missing(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE x (id INTEGER)"))
        assert add_column_if_missing(conn, "x", "extra", "TEXT") is True
        assert add_column_if_missing(conn, "x", "extra", "TEXT") is False
        assert add_column_if_missing(conn, "no_such_table", "c", "TEXT") is False
