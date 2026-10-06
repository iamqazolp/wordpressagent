import pytest

from core import wp_client
from services import sites as svc
from services.errors import ServiceError
from ui import tab_sites as ui


@pytest.fixture
def logos(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "LOGOS_DIR", tmp_path / "logos")
    return tmp_path


def _logo(tmp_path, name="up.PNG"):
    p = tmp_path / name
    p.write_bytes(b"png")
    return str(p)


def _add(name="shop", url="https://shop.example.com", **kw):
    args = dict(client_key="ck_123456789abc", client_secret="cs_secret", wp_user="", wp_app_password="",
                watermark_source=None, watermark_position="", watermark_opacity=0, current_name=None)
    args.update(kw)
    return svc.save_site(name, url, args["client_key"], args["client_secret"], args["wp_user"],
                         args["wp_app_password"], args["watermark_source"], args["watermark_position"],
                         args["watermark_opacity"], args["current_name"])


def test_create_and_read_back_with_defaults(mem_db, logos):
    assert _add() == ("shop", True)
    cfg = svc.get_site_config("shop")
    assert cfg["client_key"] == "ck_123456789abc" and cfg["client_secret"] == "cs_secret"   # mã hóa/giải mã đúng
    assert cfg["watermark_position"] == "bottom-right" and cfg["watermark_opacity"] == 0.7
    assert svc.list_site_names() == ["shop"]
    assert svc.get_site_config("ghost") is None
    assert list(svc.get_site_configs()) == ["shop"]


def test_overview_masks_key_and_flags(mem_db, logos):
    _add(wp_user="u", wp_app_password="p")
    (o,) = svc.list_sites_overview()
    assert o.client_key_preview == "ck_12345" and o.has_wp_credentials is True and o.watermark_path == ""
    assert "cs_secret" not in repr(o)


@pytest.mark.parametrize("name,url", [("", "https://x"), ("x", ""), ("  ", "  ")])
def test_save_requires_name_and_url(mem_db, logos, name, url):
    with pytest.raises(ServiceError, match="tên website và URL"):
        _add(name=name, url=url)


def test_duplicate_and_rename_rules(mem_db, logos):
    _add("a")
    _add("b", "https://b.example.com")
    with pytest.raises(ServiceError, match="đã tồn tại"):
        _add("a")
    with pytest.raises(ServiceError, match="đã được sử dụng"):
        _add("a", current_name="b")
    with pytest.raises(ServiceError, match="Không tìm thấy"):
        _add("z", current_name="ghost")
    assert _add("b2", "https://b2.example.com", current_name="b") == ("b2", False)
    assert sorted(svc.list_site_names()) == ["a", "b2"]


def test_watermark_saved_only_after_validation_and_kept_on_update(mem_db, logos):
    src = _logo(logos)
    with pytest.raises(ServiceError):
        _add("dup", url="", watermark_source=src)
    assert not (logos / "logos").exists()                      # lỗi → không sao chép file thừa

    _add("Shop A", watermark_source=src, watermark_position="top-left", watermark_opacity=0.5)
    (o,) = svc.list_sites_overview()
    assert o.watermark_path.endswith("shop_a_watermark.png") and o.watermark_position == "top-left"
    assert svc.get_watermark_preview("Shop A") == o.watermark_path

    _add("Shop A", current_name="Shop A")                       # cập nhật không kèm logo → giữ logo cũ
    assert svc.get_watermark_preview("Shop A") == o.watermark_path


def test_clear_watermark_removes_file(mem_db, logos):
    _add("s", watermark_source=_logo(logos))
    path = svc.get_watermark_preview("s")
    svc.clear_watermark("s")
    assert svc.get_watermark_preview("s") is None
    from pathlib import Path
    assert not Path(path).exists()
    with pytest.raises(ServiceError, match="Không tìm thấy"):
        svc.clear_watermark("ghost")


def test_delete_rules(mem_db, logos):
    _add("a")
    with pytest.raises(ServiceError, match="website cuối cùng"):
        svc.delete_site("a")
    _add("b", "https://b.example.com")
    svc.delete_site("a")
    assert svc.list_site_names() == ["b"]
    with pytest.raises(ServiceError, match="Không tìm thấy"):
        svc.delete_site("a")


def test_connection(monkeypatch):
    with pytest.raises(ServiceError, match="điền đủ"):
        svc.test_connection("", "k", "s")
    monkeypatch.setattr(wp_client, "test_connection", lambda cfg: {"wc_ok": True, "wp_ok": False})
    r = svc.test_connection("https://x", "k", "s", "u", "p")
    assert (r.wc_ok, r.wp_ok, r.wp_configured) == (True, False, True)
    assert svc.test_connection("https://x", "k", "s").wp_configured is False


# ── lớp UI giữ nguyên hợp đồng cũ ───────────────────────────────────────────

def test_ui_table_and_select(mem_db, logos):
    assert ui.get_sites_table_md() == "*Chưa có website nào được cấu hình.*"
    _add(wp_user="u", wp_app_password="p")
    md = ui.get_sites_table_md()
    assert "**shop**" in md and "`ck_12345...`" in md and "✅ Đã cấu hình" in md and "Chưa có |" in md
    out = ui.on_select_site_for_edit("shop")
    assert out[0] == "shop" and out[6] == "bottom-right" and out[7] == 0.7 and out[10].startswith("Đang xem")
    assert ui.on_select_site_for_edit("➕ Thêm website mới")[10] == "Điền thông tin để thêm website mới."
    assert ui.on_select_site_for_edit("ghost")[10] == "Không tìm thấy dữ liệu website."


def test_ui_save_delete_flow(mem_db, logos):
    new = "➕ Thêm website mới"
    r = ui.handle_save_site("", "", "k", "s", "", "", None, "", 0, new)
    assert r[0] == "❌ Vui lòng nhập tên website và URL!" and len(r) == 6

    r = ui.handle_save_site("shop", "https://s", "k", "s", "", "", None, "", 0, new)
    assert r[0] == "✅ Đã thêm website mới: shop" and r[2]["value"] == "shop" and r[3]["value"] == ["shop"]

    r = ui.handle_save_site("shop", "https://s", "k", "s", "", "", None, "", 0, new)
    assert r[0] == "❌ Tên website 'shop' đã tồn tại!" and r[2]["value"] == new

    r = ui.handle_save_site("shop", "https://s2", "k", "s", "", "", None, "", 0, "shop")
    assert r[0] == "✅ Đã cập nhật website: shop"

    assert ui.handle_delete_site(new)[0].startswith("❌ Vui lòng chọn")
    r = ui.handle_delete_site("shop")
    assert r[0] == "❌ Không thể xóa website 'shop' (có thể đây là website cuối cùng)." and len(r) == 5
    assert ui.handle_clear_watermark(new)[0].startswith("❌ Vui lòng chọn")
    assert ui.handle_clear_watermark("shop")[0] == "✅ Đã xóa logo watermark của website 'shop'."


def test_ui_test_connection_messages(monkeypatch):
    assert ui.handle_test_connection_ui("", "", "", "", "").startswith("❌ Vui lòng điền đủ")
    monkeypatch.setattr(wp_client, "test_connection", lambda cfg: {"wc_ok": True, "wp_ok": True})
    msg = ui.handle_test_connection_ui("https://x", "k", "s", "u", "p")
    assert msg.startswith("✅ Kết nối WooCommerce thành công tới https://x!") and "user: u" in msg
    monkeypatch.setattr(wp_client, "test_connection", lambda cfg: {"wc_ok": False, "wp_ok": False})
    msg = ui.handle_test_connection_ui("https://x", "k", "s", "", "")
    assert msg.startswith("❌ Không thể kết nối WooCommerce") and "Chưa có Application Password" in msg


def test_normalize_url():
    assert svc.normalize_url("example.com") == "https://example.com"
    assert svc.normalize_url("http://example.com/") == "http://example.com"
    assert svc.normalize_url("https://example.com///") == "https://example.com"
    assert svc.normalize_url("") == ""
    assert svc.normalize_url("   ") == ""


def test_connection_normalizes_bare_url(monkeypatch):
    called_cfg = {}
    monkeypatch.setattr(wp_client, "test_connection", lambda cfg: called_cfg.update(cfg) or {"wc_ok": True})
    svc.test_connection("khodentrangtri.com", "ck_test", "cs_test")
    assert called_cfg["url"] == "https://khodentrangtri.com"
