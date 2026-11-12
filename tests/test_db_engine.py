"""SQLite: chờ khoá thay vì báo lỗi ngay, bật WAL (Windows khoá file chặt hơn nên dễ gặp 'database is locked')."""
from sqlalchemy import create_engine, event, text

from db import database


def test_app_engine_registers_pragma_listener():
    assert event.contains(database.engine, "connect", database._sqlite_pragmas)


def test_pragmas_enable_wal_and_busy_timeout(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    event.listen(eng, "connect", database._sqlite_pragmas)
    with eng.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 30000
        conn.execute(text("CREATE TABLE t (v TEXT)"))
        conn.commit()
    eng.dispose()


def test_pragma_failure_is_not_fatal():
    class Cur:
        def execute(self, *_a):
            raise RuntimeError("không hỗ trợ WAL")

        def close(self):
            pass

    class Conn:
        def cursor(self):
            return Cur()

    database._sqlite_pragmas(Conn(), None)  # không raise
