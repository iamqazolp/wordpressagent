import json

import pytest

from core import pipeline, wp_client
from db import crud
from db.models import PostHistory
from services import posts as svc
from services.errors import PublishError, ServiceError
from ui import tab_history as ui


@pytest.fixture
def world(mem_db, tmp_path, monkeypatch):
    s = mem_db()
    site = crud.create_site(s, name="shop", url="https://shop.example.com", client_key="ck", client_secret="cs",
                            wp_user="u", wp_app_password="p")
    crud.replace_site_categories(s, site.id, "product", [{"id": 1, "name": "Quạt", "parent": 0}])
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    h1 = crud.create_post_history(
        s, site_id=site.id, product_name="Quạt X", title="Quạt X", raw_html="<p>x</p>", post_type="product",
        status="saved", short_description="sd", regular_price="100", image_paths_json=json.dumps([str(img), "/nope.jpg"]),
        category_ids_json="[1]", tags_json='["quạt"]')
    h2 = crud.create_post_history(s, site_id=site.id, product_name="Bài Y", title="Y", raw_html="<p>y</p>",
                                  post_type="post", status="failed", error_message="boom")
    ids = (h1.id, h2.id)
    s.close()

    calls = {}
    monkeypatch.setattr(wp_client, "upload_images", lambda paths, cfg, **kw: calls.setdefault("up", paths) and [{"id": 7}] * len(paths))
    monkeypatch.setattr(wp_client, "ensure_tags", lambda cfg, scope, names: [11 for _ in names])

    def fake_product(**kw):
        calls["product"] = kw
        return {"post_id": 99, "post_url": "https://shop.example.com/?p=99", "edit_url": "https://shop.example.com/edit", "status": kw["status"]}

    monkeypatch.setattr(wp_client, "publish_product", fake_product)
    monkeypatch.setattr(wp_client, "publish_post", lambda **kw: calls.setdefault("post", kw) and {"post_id": 5, "post_url": "u", "edit_url": "e", "status": kw["status"]})
    return ids, calls, str(img)


# ── đọc ──────────────────────────────────────────────────────────────────────

def test_list_posts_filters_and_summaries(world):
    (h1, h2), _, _ = world
    rows = svc.list_posts()
    assert sorted(r.id for r in rows) == sorted([h1, h2])
    by_id = {r.id: r for r in rows}
    assert by_id[h1].taxonomy_summary == "📂 Quạt · 🏷️ quạt" and by_id[h1].image_count == 2
    assert by_id[h2].taxonomy_summary == "-"
    assert [r.id for r in svc.list_posts(statuses=svc.STATUS_SAVED)] == [h1]
    assert [r.id for r in svc.list_posts(statuses=svc.STATUS_FAILED)] == [h2]
    assert [r.id for r in svc.list_posts("ghost")] == []
    assert len(svc.list_posts("shop")) == 2


def test_get_post_detail_checks_files(world):
    (h1, _), _, img = world
    d = svc.get_post(h1)
    assert d.site_name == "shop" and d.category_ids == [1] and d.tags == ["quạt"]
    assert d.image_paths == [img, "/nope.jpg"] and d.existing_image_paths == [img]
    assert svc.get_post(9999) is None


def test_save_edits_and_delete(world):
    (h1, h2), _, _ = world
    d = svc.save_post_edits(h1, "  New ", " sd2 ", " 5 ", " 4 ", " <p>n</p> ", ["/x.jpg"])
    assert (d.title, d.short_description, d.regular_price, d.sale_price, d.raw_html) == ("New", "sd2", "5", "4", "<p>n</p>")
    assert d.image_paths == ["/x.jpg"]
    assert svc.save_post_edits(h1, "t", "", "", "", "h").image_paths == ["/x.jpg"]   # không ảnh mới → giữ nguyên
    with pytest.raises(ServiceError):
        svc.save_post_edits(9999, "t", "", "", "", "h")
    svc.delete_post(h2)
    with pytest.raises(ServiceError, match="Không thể xóa"):
        svc.delete_post(h2)


# ── đăng ─────────────────────────────────────────────────────────────────────

def test_publish_saved_product_applies_saved_taxonomy_and_records(world):
    (h1, _), calls, img = world
    out = svc.publish_saved_post(h1, "  Quạt X pro ", " sd ", " 100 ", "", "<p>x</p>", "Sản phẩm WooCommerce", "draft")
    kw = calls["product"]
    assert kw["category_ids"] == [1] and kw["tag_ids"] == [11] and kw["title"] == "Quạt X pro"
    assert calls["up"] == [img]                                  # ảnh không tồn tại bị loại trước khi tải
    assert (out.post_id, out.site_name, out.uploaded_count, out.image_paths) == (h1, "shop", 1, [img])
    assert out.category_warning is None
    d = svc.get_post(h1)
    assert d.status == "draft" and d.wp_post_url.endswith("p=99") and d.published_at is not None
    assert d.title == "Quạt X pro" and d.regular_price == "100"


def test_publish_scope_mismatch_drops_categories_with_warning(world):
    (h1, _), calls, _ = world
    out = svc.publish_saved_post(h1, "t", "", "", "", "<p>x</p>", "Bài viết Blog", "publish")
    assert calls["post"]["category_ids"] == []
    assert out.category_warning and "khác với loại đang đăng" in out.category_warning
    assert svc.get_post(h1).status == "published"


def test_publish_failure_raises_and_does_not_touch_db(world, monkeypatch):
    (h1, _), _, _ = world
    monkeypatch.setattr(wp_client, "publish_product", lambda **kw: (_ for _ in ()).throw(RuntimeError("WP từ chối")))
    with pytest.raises(PublishError, match="WP từ chối"):
        svc.publish_saved_post(h1, "t", "", "", "", "<p>x</p>", "product", "draft", ["/other.jpg"])
    d = svc.get_post(h1)
    assert d.status == "saved" and d.published_at is None and d.image_paths != ["/other.jpg"]


def test_publish_missing_post(world):
    with pytest.raises(ServiceError, match="Không tìm thấy bài viết"):
        svc.publish_saved_post(9999, "t", "", "", "", "h", "product", "draft")


# ── pipeline.publish_one ─────────────────────────────────────────────────────

def test_publish_one_missing_config_and_blog_without_user(monkeypatch):
    assert pipeline.publish_one("s", {}, {"title": "t"}, [], "product", "draft") == {
        "site_name": "s", "success": False, "error": "Không tìm thấy cấu hình website"}
    r = pipeline.publish_one("s", {"wp_user": ""}, {"title": "t"}, [], "post", "draft")
    assert not r["success"] and "WP_USER" in r["error"]


def test_publish_one_image_warnings(monkeypatch):
    monkeypatch.setattr(wp_client, "publish_product", lambda **kw: {"post_id": 1, "post_url": "u", "edit_url": "e", "status": "draft"})
    r = pipeline.publish_one("s", {"wp_user": "", "wp_app_password": ""}, {"title": "t"}, ["/a.jpg"], "product", "draft")
    assert r["success"] and "Chưa cấu hình WordPress" in r["image_warning"] and r["uploaded_count"] == 0
    monkeypatch.setattr(wp_client, "upload_images", lambda *a, **k: [])
    r = pipeline.publish_one("s", {"wp_user": "u", "wp_app_password": "p"}, {"title": "t"}, ["/a.jpg"], "product", "draft")
    assert "Tải ảnh thất bại" in r["image_warning"]
    monkeypatch.setattr(wp_client, "upload_images", lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
    r = pipeline.publish_one("s", {"wp_user": "u", "wp_app_password": "p"}, {"title": "t"}, ["/a.jpg"], "product", "draft")
    assert r["success"] and r["image_warning"] == "Lỗi upload ảnh: x"


# ── lớp UI giữ nguyên hợp đồng cũ ───────────────────────────────────────────

def _choice(h):
    return f"#{h} - Quạt X (shop) [Đã lưu]"


def test_ui_table_choices_select(world):
    (h1, h2), _, img = world
    df = ui.fetch_history_data()
    assert list(df.columns) == ui._TABLE_COLUMNS
    row = df[df["ID"] == h1].iloc[0]
    assert row["Loại"] == "WooCommerce" and row["Trạng thái"] == "💾 Đã lưu nháp" and row["Ảnh"] == "2 ảnh"
    assert row["Danh mục / Tag"] == "📂 Quạt · 🏷️ quạt"
    assert list(ui.fetch_history_data("shop", "❌ Lỗi")["ID"]) == [h2]
    assert ui.fetch_history_data("ghost").empty and list(ui.fetch_history_data("ghost").columns) == ui._TABLE_COLUMNS

    assert ui.get_history_post_choices("shop", "💾 Đã lưu nháp") == [f"#{h1} - Quạt X (shop) [Đã lưu]"]
    assert ui.get_history_post_choices("ghost") == ["(Chưa có bài viết nào)"]

    sel = ui.on_select_history_post(_choice(h1))
    assert sel[0] == "Quạt X" and sel[4] == "Sản phẩm WooCommerce" and sel[5] == "draft" and sel[9] == [img]
    assert f"Bài viết #{h1}" in sel[8] and "Số lượng ảnh đính kèm:** 1 ảnh" in sel[8]
    failed = ui.on_select_history_post(f"#{h2} - Bài Y (shop) [Lỗi]")
    assert failed[4] == "Bài viết Blog" and "Lỗi trước đó:** `boom`" in failed[8]
    assert ui.on_select_history_post("")[8] == "*(Chưa chọn bài viết)*"
    assert ui.on_select_history_post("#9999 - x")[8] == "❌ Không tìm thấy bài viết!"


def test_ui_save_publish_delete_messages(world):
    (h1, h2), calls, _ = world
    assert ui.on_save_history_edits("", "t", "", "", "", "h")[0] == "❌ Vui lòng chọn một bài viết để lưu!"
    assert ui.on_save_history_edits("#9999 - x", "t", "", "", "", "h")[0] == "❌ Không tìm thấy bài viết để cập nhật!"
    r = ui.on_save_history_edits(_choice(h1), "T2", "", "", "", "<p>n</p>")
    assert r[0].startswith(f"✅ **Đã lưu cập nhật thành công cho bài #{h1} (Quạt X)!**") and len(r) == 7

    assert ui.on_publish_history_post("", "t", "", "", "", "h", "product", "draft")[0] == "❌ Vui lòng chọn một bài viết để đăng!"
    assert ui.on_publish_history_post("#9999 - x", "t", "", "", "", "h", "product", "draft")[0].startswith("❌ Không tìm thấy bài viết")
    r = ui.on_publish_history_post(_choice(h1), "T2", "", "", "", "<p>n</p>", "Sản phẩm WooCommerce", "draft")
    assert r[0].startswith("### 🎉 Đăng thành công lên shop!") and "📝 Nháp" in r[0] and "Hình ảnh tải lên WP:** 1/1" in r[0]
    assert "Cảnh báo" not in r[0] and len(r) == 6 and "Ngày đăng (GMT+7)" in r[4]

    r = ui.on_publish_history_post(_choice(h1), "T2", "", "", "", "<p>n</p>", "Bài viết Blog", "publish")
    assert "Cảnh báo danh mục" in r[0]

    assert ui.on_delete_history_post("")[0] == "❌ Vui lòng chọn bài viết cần xóa!"
    assert ui.on_delete_history_post(f"#{h2} - x")[0] == f"✅ Đã xóa thành công bài viết #{h2} khỏi hệ thống."
    assert ui.on_delete_history_post(f"#{h2} - x")[0] == f"❌ Không thể xóa bài viết #{h2}."


def test_ui_publish_failure_message(world, monkeypatch):
    (h1, _), _, _ = world
    monkeypatch.setattr(wp_client, "publish_product", lambda **kw: (_ for _ in ()).throw(RuntimeError("401")))
    r = ui.on_publish_history_post(_choice(h1), "t", "", "", "", "h", "product", "draft")
    assert r[0] == "❌ Đăng thất bại: 401" and len(r) == 6


def test_history_table_shows_sale_price(mem_db):
    from db.models import PostHistory, Site
    from ui import tab_history

    s = mem_db()
    site = Site(name="shop", url="https://shop.example.com")
    s.add(site)
    s.commit()
    s.add_all([
        PostHistory(site_id=site.id, product_name="A", title="A", raw_html="", status="saved", regular_price="100", sale_price="80"),
        PostHistory(site_id=site.id, product_name="B", title="B", raw_html="", status="saved", regular_price="50", sale_price=""),
    ])
    s.commit()
    s.close()
    df = tab_history.fetch_history_data()
    assert list(df.columns)[7:9] == ["Giá gốc", "Giá KM"]
    assert dict(zip(df["Sản phẩm"], df["Giá KM"])) == {"A": "80", "B": "-"}


def test_save_post_edits_images_none_keeps_empty_clears(world, tmp_path, monkeypatch):
    from services import images as images_svc
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(images_svc, "DATA_DIR", data)
    monkeypatch.setattr(images_svc, "POST_IMAGES_DIR", data / "post_images")
    (h1, _), _, _ = world
    a = tmp_path / "new.jpg"
    a.write_bytes(b"x")
    d = svc.save_post_edits(h1, "t", "", "", "", "<p>x</p>", [str(a)])
    assert len(d.image_paths) == 1 and d.image_paths[0].startswith(str(data))
    d = svc.save_post_edits(h1, "t", "", "", "", "<p>x</p>", None)
    assert len(d.image_paths) == 1                              # None = giữ nguyên
    d = svc.save_post_edits(h1, "t", "", "", "", "<p>x</p>", [])
    assert d.image_paths == []                                   # [] = xoá hết


def test_publish_saved_post_passes_image_options(world, monkeypatch):
    (h1, _), _, _ = world
    seen = {}
    real = pipeline.publish_one
    monkeypatch.setattr(pipeline, "publish_one", lambda *a, **kw: seen.update(kw) or real(*a, **kw))
    svc.publish_saved_post(h1, "t", "", "", "", "<p>x</p>", "product", "draft",
                           optimize_images=True, apply_watermark=False, remove_bg=True)
    assert seen["apply_watermark"] is False and seen["remove_bg"] is True and seen["optimize_images"] is True
    seen.clear()
    svc.publish_saved_post(h1, "t", "", "", "", "<p>x</p>", "product", "draft")
    assert seen["apply_watermark"] is True and seen["remove_bg"] is False


def test_history_select_warns_about_processed_images(world, tmp_path, monkeypatch):
    from services import images as images_svc
    monkeypatch.setattr(images_svc, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(images_svc, "POST_IMAGES_DIR", tmp_path / "data" / "post_images")
    (h1, _), _, _ = world
    baked = tmp_path / "x_optimized.webp"
    baked.write_bytes(b"x")
    svc.save_post_edits(h1, "t", "", "", "", "<p>x</p>", [str(baked)])
    info = ui.on_select_history_post(f"#{h1} - t")[8]
    assert "_optimized" in info and "watermark" in info
