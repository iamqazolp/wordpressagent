import pytest

from db.models import PromptTemplate
from services import templates as svc
from services.errors import ServiceError
from ui import tab_templates as ui


@pytest.fixture
def seeded(mem_db):
    s = mem_db()
    s.add_all([
        PromptTemplate(name="A", content="aaa", category="general", is_default=True),
        PromptTemplate(name="B", content="bbb", category="industrial", is_default=False),
    ])
    s.commit()
    s.close()
    return mem_db


def test_list_and_get(seeded):
    assert svc.list_template_names() == ["A", "B"]
    t = svc.get_template("B")
    assert (t.name, t.category, t.content, t.is_default) == ("B", "industrial", "bbb", False)
    assert svc.get_template("zzz") is None


def test_get_template_content(seeded):
    assert svc.get_template_content("A") == "aaa"
    assert svc.get_template_content("(Mặc định)") is None
    assert svc.get_template_content(None) is None
    assert svc.get_template_content("missing") is None


@pytest.mark.parametrize("name,content,msg", [
    ("", "x", "Tên template không được để trống."),
    ("  ", "x", "Tên template không được để trống."),
    ("N", "", "Nội dung template không được để trống."),
    ("N", "   ", "Nội dung template không được để trống."),
])
def test_save_validation(seeded, name, content, msg):
    with pytest.raises(ServiceError) as e:
        svc.save_template(name, "general", content, False)
    assert e.value.message == msg


def test_create_duplicate_and_default_switch(seeded):
    with pytest.raises(ServiceError, match="đã tồn tại"):
        svc.save_template("A", "general", "x", False)
    t, created = svc.save_template("C", "custom", "ccc", True)
    assert created and t.is_default
    assert [x.name for x in svc.list_templates() if x.is_default] == ["C"]   # mặc định cũ bị bỏ


def test_update_rename_and_conflicts(seeded):
    t, created = svc.save_template("B2", "fashion", "new", False, current_name="B")
    assert not created and t.name == "B2" and t.category == "fashion"
    with pytest.raises(ServiceError, match="mới đã tồn tại"):
        svc.save_template("A", "general", "x", False, current_name="B2")
    with pytest.raises(ServiceError, match="Không tìm thấy"):
        svc.save_template("Z", "general", "x", False, current_name="ghost")


def test_delete_rules(seeded):
    with pytest.raises(ServiceError, match="Không tìm thấy"):
        svc.delete_template("ghost")
    svc.delete_template("B")
    with pytest.raises(ServiceError, match="Có lỗi"):   # template cuối cùng không xóa được
        svc.delete_template("A")
    assert svc.list_template_names() == ["A"]


# ── lớp UI giữ nguyên hợp đồng cũ ───────────────────────────────────────────

def test_ui_select_save_delete(seeded):
    assert ui.on_select_template("➕ Tạo mới") == ("", "general", "", False, "")
    assert ui.on_select_template("A") == ("A", "general", "aaa", True, "")
    assert ui.on_select_template("ghost")[4] == "❌ Không tìm thấy template."

    msg, drop, val, create_drop = ui.handle_save_template("", "general", "x", False, "➕ Tạo mới")
    assert msg == "❌ Tên template không được để trống."

    msg, drop, val, create_drop = ui.handle_save_template("N", "custom", "n", False, "➕ Tạo mới")
    assert msg == "✅ Đã tạo template thành công." and val == "N"
    assert drop.choices[0][0] == "➕ Tạo mới" and ("N", "N") in drop.choices
    assert create_drop.choices[0][0] == "(Mặc định)"

    msg, *_ = ui.handle_save_template("N", "custom", "n2", False, "N")
    assert msg == "✅ Đã cập nhật template thành công."

    msg, drop, val, _ = ui.handle_delete_template("N")
    assert msg == "✅ Đã xóa template thành công." and val == "➕ Tạo mới"
    assert ui.handle_delete_template("➕ Tạo mới")[0] == "❌ Vui lòng chọn một template để xóa."
