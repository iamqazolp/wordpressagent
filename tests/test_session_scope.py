import pytest

from db.database import session_scope
from db.models import Site


def test_session_scope_reads_patched_factory_and_closes(mem_db):
    with session_scope() as db:
        db.add(Site(name="a", url="https://a.example"))
        db.commit()
        keep = db
    with session_scope() as db2:
        assert db2.query(Site).count() == 1
    assert db2 is not keep


def test_session_scope_rolls_back_on_error(mem_db):
    with pytest.raises(RuntimeError):
        with session_scope() as db:
            db.add(Site(name="b", url="https://b.example"))
            db.flush()
            raise RuntimeError("boom")
    with session_scope() as db:
        assert db.query(Site).count() == 0
