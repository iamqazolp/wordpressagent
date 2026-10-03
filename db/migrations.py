"""
db/migrations.py
Cơ chế migration có version cho SQLite (không cần Alembic).

Cách dùng khi đổi schema:
  1. Sửa model trong db/models.py (DB mới sẽ có cột/bảng ngay nhờ create_all).
  2. Thêm 1 hàm migration idempotent vào MIGRATIONS với version = (số lớn nhất hiện tại + 1)
     để nâng cấp DB đã tồn tại. KHÔNG sửa hay đổi số của migration đã phát hành.
"""
from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

Migration = tuple[int, str, Callable[[Connection], None]]


def table_exists(conn: Connection, table: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:t"), {"t": table}
    ).fetchone()
    return row is not None


def column_names(conn: Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def add_column_if_missing(conn: Connection, table: str, column: str, ddl_type: str) -> bool:
    """Thêm cột nếu chưa có. Trả về True nếu đã thêm. Bỏ qua nếu bảng chưa tồn tại."""
    if not table_exists(conn, table):
        return False
    if column in column_names(conn, table):
        return False
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
    logger.info(f"Migration: đã thêm cột {table}.{column}")
    return True


# ── Các migration ────────────────────────────────────────────

def _m001_baseline_columns(conn: Connection) -> None:
    """Gộp các ALTER TABLE rải rác trước đây (Phase 2: post_history, Phase 3.1: sites)."""
    for col, ddl in [
        ("short_description", "TEXT"),
        ("regular_price", "VARCHAR(50)"),
        ("sale_price", "VARCHAR(50)"),
        ("image_paths_json", "TEXT"),
    ]:
        add_column_if_missing(conn, "post_history", col, ddl)

    for col, ddl in [
        ("watermark_path", "VARCHAR(500) DEFAULT ''"),
        ("watermark_position", "VARCHAR(50) DEFAULT 'bottom-right'"),
        ("watermark_opacity", "FLOAT DEFAULT 0.7"),
    ]:
        add_column_if_missing(conn, "sites", col, ddl)


MIGRATIONS: list[Migration] = [
    (1, "baseline_columns", _m001_baseline_columns),
]


# ── Runner ───────────────────────────────────────────────────

def get_schema_version(conn: Connection) -> int:
    if not table_exists(conn, "schema_version"):
        return 0
    row = conn.execute(text("SELECT MAX(version) FROM schema_version")).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def run_migrations(engine: Engine, migrations: list[Migration] | None = None) -> int:
    """
    Chạy tuần tự các migration chưa áp dụng. Mỗi migration chạy trong 1 transaction riêng:
    lỗi thì rollback migration đó và DỪNG (không bỏ qua rồi chạy tiếp migration sau).
    Trả về version hiện tại sau khi chạy.
    """
    migrations = sorted(migrations if migrations is not None else MIGRATIONS, key=lambda m: m[0])
    versions = [m[0] for m in migrations]
    if len(versions) != len(set(versions)):
        raise ValueError("Có version migration bị trùng.")

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_version ("
                "version INTEGER PRIMARY KEY, name VARCHAR(200), applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        current = get_schema_version(conn)

    for version, name, fn in migrations:
        if version <= current:
            continue
        try:
            _apply_atomically(engine, version, name, fn)
            logger.info(f"Migration #{version} ({name}) đã áp dụng.")
            current = version
        except Exception:
            logger.exception(f"Migration #{version} ({name}) thất bại — dừng lại, giữ nguyên version {current}.")
            raise

    return current


def _apply_atomically(engine: Engine, version: int, name: str, fn: Callable[[Connection], None]) -> None:
    """
    pysqlite mặc định tự COMMIT trước mỗi lệnh DDL nên rollback không hoàn tác được CREATE/ALTER.
    Tắt chế độ tự quản transaction của driver và tự BEGIN/COMMIT để cả migration là 1 khối nguyên tử.
    """
    with engine.connect() as conn:
        dbapi = conn.connection.driver_connection
        old_level = dbapi.isolation_level
        dbapi.isolation_level = None
        try:
            conn.exec_driver_sql("BEGIN")
            try:
                fn(conn)
                conn.execute(
                    text("INSERT INTO schema_version (version, name) VALUES (:v, :n)"),
                    {"v": version, "n": name},
                )
                conn.exec_driver_sql("COMMIT")
            except Exception:
                conn.exec_driver_sql("ROLLBACK")
                raise
        finally:
            dbapi.isolation_level = old_level
