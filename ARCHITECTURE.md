# Kiến trúc

```
ui/ (Gradio)  ──►  services/  ──►  core/  ──►  db/
   │                  │              │
   │                  │              └─ WordPress client, Gemini, ảnh, scheduler, pipeline
   │                  └─ nghiệp vụ, trả dataclass/dict thuần
   └─ chỉ dựng widget, gom input, đổi kết quả thành gr.update / Markdown
```

Mục tiêu: **đổi giao diện (hoặc thêm REST API) mà không viết lại nghiệp vụ.** Gradio chỉ nằm trong `ui/` và `app.py`.

## Quy tắc (được test tự động trong [tests/test_architecture.py](tests/test_architecture.py))

1. `services/`, `core/`, `db/` **không import** `gradio` (hay framework UI khác).
2. `ui/` **không import** `db/` — mọi truy cập dữ liệu đi qua `services/`.
3. Không import ngược chiều: `services/`, `core/` không import `ui/`; `core/`, `db/` không import `services/`
   (`db/` chỉ dùng helper thuần `core.timeutil`).

Quy ước khác (không có test, nhưng hãy giữ):

4. Service tự mở session bằng `db.database.session_scope()` và trả **dataclass/dict**, không trả ORM object.
5. Tiến độ truyền qua callback `progress(value, text)` do nơi gọi cung cấp.
6. Lỗi nghiệp vụ dự kiến → `raise ServiceError("thông điệp")` ([services/errors.py](services/errors.py)). UI hiển thị `"❌ {thông điệp}"`.
   `PublishError` (con của `ServiceError`) = đăng WordPress thất bại.
7. Toast (`gr.Info`), Markdown báo cáo, `gr.update` chỉ ở `ui/`.
8. Hàm handler trong `ui/` **giữ nguyên tên/chữ ký** vì `api_name` của Gradio lấy từ tên hàm và `/config` phụ thuộc vào đó.
   Kiểm tra bằng `python tools/wiring_snapshot.py` (so với bản trước khi sửa).
9. Dữ liệu `articles_state` giữ nguyên dạng: `{site: {title, raw_html, short_description, product_name, category_ids, tags, category_scope, preview_html(chỉ ui)}}`.

## Bản đồ module

| Lĩnh vực | `ui/` (mỏng) | `services/` | Ghi chú |
|---|---|---|---|
| Template | `tab_templates.py` | `templates.py` | |
| Website | `tab_sites.py` | `sites.py` | kiểm tra kết nối, watermark |
| Tạo bài | `tab_create.py` | `generation.py`, `images.py`, `publishing.py`, `schedules.schedule_post` | |
| Hàng loạt | `tab_bulk.py` | `bulk.py` | CSV/Excel |
| Kho bài | `tab_history.py` | `posts.py` | đăng lại bài đã lưu dùng chung `core.pipeline.publish_one` |
| Lịch đăng | `tab_scheduler.py` | `schedules.py` | giờ GMT+7 naive |
| Danh mục & tag | `taxonomy_panel.py`, `taxonomy_records.py` | `taxonomy.py` (`TaxControls`), `schedules.py` | UI đổi `TaxControls` → `gr.update` |

## Thêm một tính năng

1. Viết logic trong `services/<tên>.py` (hàm thuần, nhận/trả dữ liệu đơn giản, tự `session_scope()`).
2. Test bằng fixture `mem_db` ([tests/conftest.py](tests/conftest.py)) — không cần gradio, không cần mạng (mock `core/wp_client`, Gemini).
3. Thêm handler mỏng trong `ui/` gọi service; nối sự kiện ở `ui/main_ui.py`.
4. Chạy `pytest` (gồm test kiến trúc) và `tools/wiring_snapshot.py`.

## Đổi UI sau này

Giữ nguyên `services/` + `core/` + `db/`. Viết lớp giao diện mới (hoặc `api/` FastAPI) gọi trực tiếp `services/*`. Chỗ duy nhất
chứa logic trình bày cần viết lại là `ui/` (định dạng bảng, `gr.update`, Markdown).
