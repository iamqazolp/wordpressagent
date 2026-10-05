import json

import pandas as pd
import pytest

from core import pipeline, wp_client
from db import crud
from services import bulk, generation, images, publishing
from services.errors import ServiceError
from ui import tab_bulk, tab_create


@pytest.fixture
def world(mem_db, tmp_path, monkeypatch):
    s = mem_db()
    for name in ("shop", "blog"):
        crud.create_site(s, name=name, url=f"https://{name}.example.com", client_key="ck", client_secret="cs",
                         wp_user="u", wp_app_password="p")
    crud.create_template(s, name="T1", content="TEMPLATE-BODY", category="general", is_default=True)
    s.close()
    monkeypatch.setattr(wp_client, "ensure_tags", lambda cfg, scope, names: [1 for _ in names])
    return tmp_path


@pytest.fixture
def fake_ai(monkeypatch):
    seen = {}

    def gen(**kw):
        seen.update(kw)
        return {name: {"title": f"T-{name}", "raw_html": "<p>x</p><table><tr><td>spec</td></tr></table>"}
                for name in kw["selected_sites"]}

    monkeypatch.setattr(pipeline, "generate_articles", gen)
    return seen


@pytest.fixture
def fake_wp(monkeypatch):
    calls = []

    def product(**kw):
        calls.append(kw)
        return {"post_id": len(calls), "post_url": f"https://x/?p={len(calls)}", "edit_url": "e", "status": kw["status"]}

    monkeypatch.setattr(wp_client, "publish_product", product)
    monkeypatch.setattr(wp_client, "check_wp_credentials", lambda cfg, **k: None)
    monkeypatch.setattr(wp_client, "upload_images", lambda paths, cfg, **kw: [{"id": 1}] * len(paths))
    return calls


# ── generation ───────────────────────────────────────────────────────────────

def test_extract_short_description():
    assert generation.extract_short_description("<p>a</p><TABLE class='x'><tr></tr></TABLE>").startswith("<TABLE")
    assert generation.extract_short_description("<p>no table</p>") == ""
    assert generation.extract_short_description("") == ""


def test_generate_validates_and_enriches(world, fake_ai):
    with pytest.raises(ServiceError, match="tên sản phẩm"):
        generation.generate_for_sites("  ", ["shop"])
    with pytest.raises(ServiceError, match="ít nhất 1 website"):
        generation.generate_for_sites("Quạt", [])

    arts = generation.generate_for_sites("Quạt", ["shop", "ghost"], image_paths=[], extra_urls=["u"],
                                         user_notes="n", randomize=True, template_name="T1")
    assert list(arts) == ["shop"]                                     # site không tồn tại bị bỏ qua
    assert arts["shop"]["product_name"] == "Quạt" and arts["shop"]["short_description"].startswith("<table")
    assert fake_ai["template_content"] == "TEMPLATE-BODY" and fake_ai["image_files"] is None
    assert fake_ai["randomize_enabled"] is True and fake_ai["extra_urls"] == ["u"]

    generation.generate_for_sites("Quạt", ["shop"], template_name="(Mặc định)")
    assert fake_ai["template_content"] is None


def test_generate_empty_result(world, monkeypatch):
    monkeypatch.setattr(pipeline, "generate_articles", lambda **kw: {})
    with pytest.raises(ServiceError, match="Không tạo được"):
        generation.generate_for_sites("Quạt", ["shop"])


def test_ui_run_pipeline_messages(world, fake_ai):
    drop, *rest = tab_create.run_pipeline_ui("", None, "", "", ["shop"], False, "(Mặc định)")
    assert rest[-1] == "❌ Vui lòng nhập tên sản phẩm!" and rest[3] == {}
    out = tab_create.run_pipeline_ui("Quạt", None, "http://a\n\n http://b ", "", ["shop"], False, "T1")
    drop, title, short, preview, state, site, msg = out
    assert title == "T-shop" and site == "shop" and msg.startswith("✅ Đã tạo bài cho 1 website")
    assert state["shop"]["preview_html"] == preview and fake_ai["extra_urls"] == ["http://a", "http://b"]


# ── publishing ───────────────────────────────────────────────────────────────

def _articles(**extra):
    base = {"title": "Quạt X", "raw_html": "<p>x</p>", "short_description": "sd", "product_name": "Quạt"}
    base.update(extra)
    return {"shop": dict(base), "blog": dict(base)}


def test_publish_and_record_writes_history(world, fake_wp):
    from services import posts
    arts = _articles(category_ids=[5], category_scope="product", tags=["t"])
    results = publishing.publish_and_record(arts, ["/missing.jpg"], "Sản phẩm WooCommerce", "draft", "10", "8")
    assert [r["success"] for r in results] == [True, True]
    rows = posts.list_posts()
    assert {r.status for r in rows} == {"draft"} and {r.post_type for r in rows} == {"product"}
    d = posts.get_post(rows[0].id)
    assert d.category_ids == [5] and d.tags == ["t"] and d.regular_price == "10" and d.wp_post_url.startswith("https://x/?p=")
    assert fake_wp[0]["category_ids"] == [5]


def test_publish_and_record_failure_recorded(world, monkeypatch):
    from services import posts
    monkeypatch.setattr(wp_client, "publish_product", lambda **kw: (_ for _ in ()).throw(RuntimeError("down")))
    results = publishing.publish_and_record(_articles(), [], "product", "draft")
    assert all(not r["success"] for r in results)
    rows = posts.list_posts()
    assert {r.status for r in rows} == {"failed"}
    assert posts.get_post(rows[0].id).error_message == "down"


def test_save_drafts_keeps_original_images_per_site(world, monkeypatch, tmp_path):
    from services import posts
    monkeypatch.setattr(images, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(images, "POST_IMAGES_DIR", tmp_path / "data" / "post_images")
    called = []
    monkeypatch.setattr(images, "process_image_batch", lambda *a, **k: called.append(1) or [])
    res = publishing.save_drafts(_articles(), ["/a.jpg"], "Bài viết Blog", "1", "2")
    assert (res.saved_count, res.image_count) == (2, 1) and called == []   # không xử lý/đóng watermark lúc lưu
    rows = posts.list_posts()
    assert {r.status for r in rows} == {"saved"} and {r.post_type for r in rows} == {"post"}
    assert [posts.get_post(r.id).image_paths for r in rows] == [["/a.jpg"], ["/a.jpg"]]
    assert publishing.save_drafts({"ghost": _articles()["shop"]}, ["/a.jpg"], "product").saved_count == 0


def test_preview_processed_options(world, monkeypatch):
    seen = {}
    monkeypatch.setattr(images, "process_image_batch", lambda paths, options: seen.update(options) or [{"output_path": "o.webp"}])
    out, res = images.preview_processed(["/a.jpg"], "shop", optimize=False, watermark=True, remove_bg=True)
    assert out == ["o.webp"] and seen["format"] == "JPEG" and seen["max_width"] == 9999 and seen["remove_bg"] is True
    assert seen["watermark_path"] is None                           # site chưa có logo
    images.preview_processed(["/a.jpg"], None, optimize=True, watermark=True, remove_bg=False)
    assert seen["format"] == "WEBP" and seen["max_width"] == 1200 and seen["watermark_path"] is None


def test_ui_publish_report_and_save_messages(world, fake_wp):
    assert tab_create.publish_to_sites_ui({}, None, "draft", "product").startswith("❌ Chưa có nội dung")
    msg = tab_create.publish_to_sites_ui(_articles(), None, "draft", "product")
    assert msg.startswith("### 📋 Kết Quả Đăng Bài:") and "**shop**: ✅ Thành công (📝 Nháp)" in msg
    assert tab_create.save_draft_articles_ui({}, None, "product").startswith("❌ Chưa có nội dung")
    msg = tab_create.save_draft_articles_ui(_articles(), None, "product")
    assert msg.startswith("### 💾 Đã lưu 2 bài vào kho")


def test_ui_preview_processed_images_without_files():
    assert tab_create.handle_preview_processed_images(None, "shop", True, True, False)[0] is None


# ── bulk ─────────────────────────────────────────────────────────────────────

def _csv(tmp_path, text, name="p.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_parse_csv_aliases_and_nan(tmp_path):
    f = _csv(tmp_path, "Tên sản phẩm,URL,Ghi chú,Giá gốc,Giá KM\nQuạt A,http://a,note,100,nan\n,x,,,\nQuạt B,,,,\n")
    products, kind = bulk.parse_product_file(f)
    assert kind == "CSV" and [p["product_name"] for p in products] == ["Quạt A", "Quạt B"]
    assert products[0] == {"product_name": "Quạt A", "ref_urls": "http://a", "notes": "note", "regular_price": "100", "sale_price": ""}


def test_parse_errors(tmp_path):
    with pytest.raises(ServiceError, match="File rỗng"):
        bulk.parse_product_file(_csv(tmp_path, ""))
    with pytest.raises(ServiceError, match="Không tìm thấy dòng dữ liệu hợp lệ"):
        bulk.parse_product_file(_csv(tmp_path, "foo,bar\n1,2\n"))
    with pytest.raises(ServiceError, match="Lỗi đọc file"):
        bulk.parse_product_file(str(tmp_path / "missing.xlsx"))


def test_parse_excel(tmp_path):
    p = tmp_path / "p.xlsx"
    pd.DataFrame({"product_name": ["Quạt Z"], "price": ["9"]}).to_excel(p, index=False)
    products, kind = bulk.parse_product_file(str(p))
    assert kind == "Excel" and products[0]["product_name"] == "Quạt Z" and products[0]["regular_price"] == "9"


def test_split_reference_urls():
    assert bulk.split_reference_urls("http://a; http://b,\nftp://c , nope") == ["http://a", "http://b"]
    assert bulk.split_reference_urls("") == []


def test_bulk_generate_and_save_keeps_going_on_error(world, monkeypatch):
    from services import posts
    calls = []

    def gen(**kw):
        calls.append(kw["product_name"])
        if kw["product_name"] == "Lỗi":
            raise RuntimeError("AI hết quota")
        return {n: {"title": "t", "raw_html": "<p>x</p>"} for n in kw["selected_sites"]}

    monkeypatch.setattr(pipeline, "generate_articles", gen)
    res = bulk.generate_and_save(
        [{"product_name": "A", "regular_price": "5"}, {"product_name": "Lỗi"}, {"product_name": "B"}], ["shop"], None, False)
    assert [r["status"] for r in res] == ["success", "error", "success"] and res[1]["error"] == "AI hết quota"
    rows = posts.list_posts()
    assert len(rows) == 2 and {r.status for r in rows} == {"saved"} and {r.post_type for r in rows} == {"product"}
    with pytest.raises(ServiceError):
        bulk.generate_and_save([], ["shop"], None, False)
    with pytest.raises(ServiceError):
        bulk.generate_and_save([{"product_name": "A"}], [], None, False)


def test_bulk_generate_and_publish_rows(world, fake_ai, monkeypatch):
    from services import posts

    def product(**kw):
        if kw["title"] == "T-blog":
            raise RuntimeError("401")
        return {"post_id": 1, "post_url": "https://x/p", "edit_url": "e", "status": "draft"}

    monkeypatch.setattr(wp_client, "publish_product", product)
    rows = bulk.generate_and_publish([{"product_name": "A", "regular_price": "7"}], ["shop", "blog"], None, False, "product", "draft")
    kinds = {(r.site_name, r.kind) for r in rows}
    assert kinds == {("shop", "published"), ("blog", "publish_failed")}
    assert {r.status for r in posts.list_posts()} == {"draft", "failed"}
    assert all(p.regular_price == "7" for p in posts.list_posts())      # lịch sử hàng loạt giờ có cả giá


def test_bulk_generate_and_publish_create_failure(world, monkeypatch):
    monkeypatch.setattr(pipeline, "generate_articles", lambda **kw: (_ for _ in ()).throw(RuntimeError("no key")))
    (row,) = bulk.generate_and_publish([{"product_name": "A"}], ["shop"], None, False, "product", "draft")
    assert (row.kind, row.detail) == ("create_failed", "no key")


def test_ui_bulk_contract(world, fake_ai, fake_wp, tmp_path):
    df, state, msg = tab_bulk.parse_csv_file(None)
    assert df.empty and state == [] and msg == "❌ Vui lòng tải lên file CSV hoặc Excel."
    df, state, msg = tab_bulk.parse_csv_file(_csv(tmp_path, "product_name,price\nQuạt A,100\n"))
    assert msg == "✅ Đã tải thành công 1 sản phẩm từ file CSV!" and list(df.columns)[0] == "Tên sản phẩm" and df.iloc[0]["Giá gốc"] == "100"

    assert tab_bulk.run_bulk_generate([], ["shop"], "(Mặc định)", False)[2].startswith("❌ Không có sản phẩm")
    results, table, msg = tab_bulk.run_bulk_generate(state, ["shop", "blog"], "(Mặc định)", False)
    assert [r["status"] for r in results] == ["success"] and len(table) == 2
    assert list(table.columns) == tab_bulk._RESULT_COLUMNS and table.iloc[0]["Trạng thái"] == "💾 Đã lưu nháp trên Web"
    assert msg.startswith("### 💾 Hoàn tất tạo và lưu nháp bài viết cho 1 sản phẩm")

    assert tab_bulk.run_bulk_generate_and_publish(state, [], "(Mặc định)", False, "product", "draft")[1].startswith("❌ Vui lòng chọn")
    table, msg = tab_bulk.run_bulk_generate_and_publish(state, ["shop"], "(Mặc định)", False, "product", "draft")
    assert table.iloc[0]["Trạng thái"] == "✅ Đăng thành công (draft)" and msg == "🎉 Hoàn tất quá trình tạo và đăng cho 1 sản phẩm!"
    assert tab_bulk.load_sites() == ["shop", "blog"] and tab_bulk.load_templates()[0] == "(Mặc định)"


def test_short_description_note(world, fake_ai, monkeypatch):
    from core import ai_writer

    calls = []
    monkeypatch.setattr(ai_writer, "write_short_description", lambda name, html, note: calls.append(note) or "<p>AI</p>")
    arts = generation.generate_for_sites("Quạt", ["shop"])
    assert arts["shop"]["short_description"].startswith("<table") and calls == []

    arts = generation.generate_for_sites("Quạt", ["shop"], short_desc_note="  3 gạch đầu dòng ")
    assert arts["shop"]["short_description"] == "<p>AI</p>" and calls == ["3 gạch đầu dòng"]


def test_short_description_note_falls_back_to_table(world, fake_ai, monkeypatch):
    from core import ai_writer

    def boom(*a):
        raise RuntimeError("quota")

    monkeypatch.setattr(ai_writer, "write_short_description", boom)
    arts = generation.generate_for_sites("Quạt", ["shop"], short_desc_note="ngắn")
    assert arts["shop"]["short_description"].startswith("<table") and arts["shop"]["short_desc_warning"]
    *_, msg = tab_create.run_pipeline_ui("Quạt", None, "", "", ["shop"], False, "(Mặc định)", "ngắn")
    assert "⚠️" in msg
