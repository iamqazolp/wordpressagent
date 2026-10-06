"""
services/posts.py — kho bài viết (PostHistory): liệt kê, xem, sửa, xóa, đăng bài đã lưu.

Nghiệp vụ tách khỏi ui/tab_history.py. Trả dataclass thuần (không ORM). Việc đăng một bài dùng chung
core.pipeline.publish_one với luồng "Tạo & Đăng bài" để hành vi (ảnh, danh mục, tag, cảnh báo) giống hệt nhau.
"""
from __future__ import annotations

import concurrent.futures

import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core import pipeline
from core.timeutil import now_vn
from db import crud
from db.database import session_scope
from services import images as images_svc
from services import taxonomy as taxonomy_svc
from services.errors import PublishError, ServiceError

# Nhóm trạng thái dùng cho bộ lọc (giá trị `status` trong DB)
STATUS_SAVED = ("saved",)
STATUS_PUBLISHED = ("published", "draft")
STATUS_FAILED = ("failed",)


@dataclass(frozen=True)
class PostRow:
    id: int
    product_name: str
    title: str
    site_name: str
    post_type: str               # 'product' | 'post'
    status: str
    image_count: int
    regular_price: str
    sale_price: str
    category_ids: list[int]
    tags: list[str]
    taxonomy_summary: str        # '📂 A, B · 🏷️ t1' hoặc '-'
    created_at: datetime | None
    wp_post_url: str


@dataclass(frozen=True)
class PostDetail:
    id: int
    site_name: str
    site_url: str
    product_name: str
    title: str
    short_description: str
    regular_price: str
    sale_price: str
    raw_html: str
    post_type: str
    status: str
    wp_post_url: str
    error_message: str
    image_paths: list[str]           # đã lưu trong DB
    existing_image_paths: list[str]  # còn tồn tại trên ổ đĩa
    category_ids: list[int]
    tags: list[str]
    created_at: datetime | None
    published_at: datetime | None
    wp_post_id: str = ""             # rỗng nếu chưa đăng/liên kết với bài WP nào


@dataclass(frozen=True)
class PublishOutcome:
    post_id: int
    site_name: str
    post_status: str                 # 'draft' | 'publish'
    post_url: str
    edit_url: str
    uploaded_count: int
    image_paths: list[str]           # ảnh hợp lệ đã dùng để đăng
    image_warning: str | None = None
    taxonomy_warning: str | None = None
    category_warning: str | None = None
    updated: bool = False            # True: đã ghi đè bài WP có sẵn thay vì tạo mới


def _image_paths(h) -> list[str]:
    paths = taxonomy_svc.loads_list(h.image_paths_json)
    return [str(p) for p in paths]


def _detail(h) -> PostDetail:
    paths = _image_paths(h)
    return PostDetail(
        id=h.id,
        site_name=h.site.name if h.site else "Unknown",
        site_url=h.site.url if h.site else "",
        product_name=h.product_name or "",
        title=h.title or "",
        short_description=h.short_description or "",
        regular_price=h.regular_price or "",
        sale_price=h.sale_price or "",
        raw_html=h.raw_html or "",
        post_type=h.post_type or "product",
        status=h.status or "",
        wp_post_url=h.wp_post_url or "",
        error_message=h.error_message or "",
        image_paths=paths,
        existing_image_paths=[p for p in paths if Path(p).exists()],
        category_ids=taxonomy_svc.normalize_category_ids(taxonomy_svc.loads_list(h.category_ids_json)),
        tags=[str(t) for t in taxonomy_svc.loads_list(h.tags_json)],
        created_at=h.created_at,
        published_at=h.published_at,
        wp_post_id=h.wp_post_id or "",
    )


def list_posts(
    site_name: str | None = None,
    statuses: Collection[str] | None = None,
    limit: int = 200,
) -> list[PostRow]:
    """Bài mới nhất trước. `site_name` rỗng = mọi website; `statuses` rỗng = mọi trạng thái."""
    with session_scope() as db:
        site_id = None
        if site_name:
            site = crud.get_site_by_name(db, site_name)
            site_id = site.id if site else -1
        rows: list[PostRow] = []
        tax_cache: dict = {}  # tên danh mục theo (site, loại) — tránh truy vấn lặp cho từng dòng
        for h in crud.get_post_history(db, site_id=site_id, limit=limit):
            if statuses and h.status not in statuses:
                continue
            d = _detail(h)
            rows.append(PostRow(
                id=h.id,
                product_name=d.product_name,
                title=d.title,
                site_name=d.site_name,
                post_type=d.post_type,
                status=d.status,
                image_count=len(d.image_paths),
                regular_price=d.regular_price,
                sale_price=d.sale_price,
                category_ids=d.category_ids,
                tags=d.tags,
                taxonomy_summary=taxonomy_svc.summarize_selection(
                    db, d.site_name, taxonomy_svc.scope_of(d.post_type), d.category_ids, d.tags, tax_cache
                ),
                created_at=h.created_at,
                wp_post_url=d.wp_post_url,
            ))
        return rows


def get_post(post_id: int) -> PostDetail | None:
    with session_scope() as db:
        h = crud.get_post_history_by_id(db, post_id)
        return _detail(h) if h else None


def save_post_edits(
    post_id: int,
    title: str,
    short_description: str,
    regular_price: str,
    sale_price: str,
    raw_html: str,
    new_image_paths: list[str] | None = None,
) -> PostDetail:
    """
    Lưu nội dung/giá/ảnh. new_image_paths: None = giữ nguyên ảnh cũ; danh sách (kể cả rỗng) = thay thế
    toàn bộ ảnh của bài bằng danh sách này. Trả bài sau khi lưu.
    """
    with session_scope() as db:
        h = crud.get_post_history_by_id(db, post_id)
        if not h:
            raise ServiceError("Không tìm thấy bài viết để cập nhật!")
        h.title = title.strip()
        h.short_description = short_description.strip()
        h.regular_price = regular_price.strip()
        h.sale_price = sale_price.strip()
        h.raw_html = raw_html.strip()
        if new_image_paths is not None:
            h.image_paths_json = json.dumps(images_svc.persist_images(new_image_paths), ensure_ascii=False)
        db.commit()
        return _detail(h)


def delete_post(post_id: int) -> None:
    with session_scope() as db:
        if not crud.delete_post_history(db, post_id):
            raise ServiceError(f"Không thể xóa bài viết #{post_id}.")


def publish_saved_post(
    post_id: int,
    title: str,
    short_description: str,
    regular_price: str,
    sale_price: str,
    raw_html: str,
    post_type: str,
    post_status: str,
    new_image_paths: list[str] | None = None,
    update_existing: bool = False,
    optimize_images: bool = True,
    apply_watermark: bool = True,
    remove_bg: bool = False,
) -> PublishOutcome:
    """
    Đăng ngay một bài đã lưu. Danh mục/tag lấy từ bài đã lưu; id danh mục chỉ áp dụng khi cùng loại nội dung
    với lúc chọn (xem category_warning). Chỉ ghi DB khi đăng thành công.
    update_existing=True: GHI ĐÈ bài WP đã liên kết (wp_post_id) bằng PUT thay vì đăng thêm bản mới
    (raise ServiceError nếu bài chưa có wp_post_id). Ảnh được tải lên lại như khi đăng mới.
    optimize_images / apply_watermark / remove_bg: xử lý ảnh GỐC lúc đăng (nén WebP, đóng logo watermark hiện tại
    của website, tách nền). Bỏ apply_watermark để đăng ảnh không có watermark.
    Raise ServiceError (không tìm thấy/thiếu cấu hình) hoặc PublishError (WordPress từ chối/lỗi mạng).
    """
    with session_scope() as db:
        h = crud.get_post_history_by_id(db, post_id)
        if not h or not h.site:
            raise ServiceError("Không tìm thấy bài viết hoặc website cấu hình!")
        site_config = crud.get_site_config(db, h.site_id)
        if not site_config:
            raise ServiceError("Không tìm thấy thông tin xác thực của website!")

        # new_image_paths: None = dùng ảnh đã lưu; danh sách (kể cả rỗng) = bộ ảnh người dùng vừa chọn
        image_paths = images_svc.persist_images(new_image_paths) if new_image_paths is not None else _image_paths(h)
        valid_images = [p for p in image_paths if Path(p).exists()]

        existing_id = None
        if update_existing:
            existing_id = (h.wp_post_id or "").strip()
            if not existing_id:
                raise ServiceError("Bài này chưa có ID bài WordPress để cập nhật — hãy đăng mới hoặc liên kết với bài có sẵn.")

        title = title.strip()
        article = {
            "title": title or h.product_name,
            "raw_html": raw_html,
            "short_description": short_description.strip(),
            # Id category chỉ hợp lệ trong đúng loại nội dung (product/post) đã dùng khi chọn.
            "category_ids": taxonomy_svc.normalize_category_ids(taxonomy_svc.loads_list(h.category_ids_json)),
            "category_scope": taxonomy_svc.scope_of(h.post_type),
            "tags": [str(t) for t in taxonomy_svc.loads_list(h.tags_json)],
        }
        res = pipeline.publish_one(
            h.site.name, site_config, article, valid_images, post_type, post_status,
            regular_price=regular_price.strip(), sale_price=sale_price.strip(),
            existing_wp_id=existing_id,
            optimize_images=optimize_images, apply_watermark=apply_watermark, remove_bg=remove_bg,
        )
        if not res.get("success"):
            raise PublishError(res.get("error") or "Lỗi không xác định")

        if new_image_paths is not None:
            h.image_paths_json = json.dumps(image_paths, ensure_ascii=False)
        h.title = title
        h.raw_html = raw_html
        h.short_description = short_description.strip()
        h.regular_price = regular_price.strip()
        h.sale_price = sale_price.strip()
        h.status = "published" if post_status == "publish" else "draft"
        h.wp_post_id = str(res.get("post_id", ""))
        h.wp_post_url = res.get("post_url")
        h.published_at = now_vn()
        h.error_message = None
        db.commit()

        return PublishOutcome(
            post_id=h.id,
            site_name=h.site.name,
            post_status=post_status,
            post_url=res.get("post_url") or "",
            edit_url=res.get("edit_url") or "",
            uploaded_count=res.get("uploaded_count", 0),
            image_paths=valid_images,
            image_warning=res.get("image_warning"),
            taxonomy_warning=res.get("taxonomy_warning"),
            category_warning=res.get("category_warning"),
            updated=bool(existing_id),
        )


# ── Xử lý hàng loạt các bài đã lưu (tab Tạo hàng loạt) ─────────────────────────

@dataclass(frozen=True)
class BatchItem:
    post_id: int
    product_name: str
    site_name: str
    ok: bool
    detail: str = ""             # URL (đăng ngay), giờ hẹn (hẹn giờ) hoặc lỗi
    when: datetime | None = None


def publish_saved_batch(post_ids: list[int], post_status: str) -> list[BatchItem]:
    """Đăng ngay từng bài đã lưu (nội dung/ảnh/danh mục như đã lưu, xử lý ảnh mặc định). Một bài lỗi không chặn các bài khác."""
    if not post_ids:
        return []

    # Bước 1: Đọc thông tin bài viết và cấu hình website trên luồng chính
    with session_scope() as db:
        tasks_data = []
        for pid in post_ids:
            h = crud.get_post_history_by_id(db, pid)
            if not h or not h.site:
                tasks_data.append({"pid": pid, "found": False})
                continue
            site_cfg = crud.get_site_config(db, h.site_id)
            tasks_data.append({
                "pid": pid,
                "found": True,
                "site_name": h.site.name,
                "site_cfg": site_cfg,
                "product_name": h.product_name or "",
                "title": (h.title or h.product_name or "").strip(),
                "short_desc": (h.short_description or "").strip(),
                "reg_price": (h.regular_price or "").strip(),
                "sale_price": (h.sale_price or "").strip(),
                "raw_html": h.raw_html or "",
                "post_type": h.post_type,
                "wp_post_id": (h.wp_post_id or "").strip(),
                "image_paths": [p for p in _image_paths(h) if Path(p).exists()],
                "category_ids": taxonomy_svc.normalize_category_ids(taxonomy_svc.loads_list(h.category_ids_json)),
                "category_scope": taxonomy_svc.scope_of(h.post_type),
                "tags": [str(t) for t in taxonomy_svc.loads_list(h.tags_json)],
            })

    # Bước 2: Đăng song song qua ThreadPoolExecutor (không truy cập DB trong worker thread)
    def _worker(t: dict) -> dict:
        pid = t["pid"]
        if not t.get("found"):
            return {"pid": pid, "res": None, "error": "Không tìm thấy bài"}
        if not t.get("site_cfg"):
            return {"pid": pid, "res": None, "error": "Không tìm thấy thông tin xác thực của website!"}
        try:
            article = {
                "title": t["title"],
                "raw_html": t["raw_html"],
                "short_description": t["short_desc"],
                "category_ids": t["category_ids"],
                "category_scope": t["category_scope"],
                "tags": t["tags"],
            }
            res = pipeline.publish_one(
                site_name=t["site_name"],
                site_config=t["site_cfg"],
                article_data=article,
                image_paths=t["image_paths"],
                post_type=t["post_type"],
                post_status=post_status,
                regular_price=t["reg_price"],
                sale_price=t["sale_price"],
                existing_wp_id=None,
                optimize_images=True,
                apply_watermark=True,
                remove_bg=False,
            )
            if not res.get("success"):
                return {"pid": pid, "res": res, "error": res.get("error") or "Lỗi không xác định"}
            return {"pid": pid, "res": res, "error": None}
        except Exception as e:
            return {"pid": pid, "res": None, "error": str(e)}

    max_workers = min(4, len(tasks_data)) if tasks_data else 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        published_results = list(executor.map(_worker, tasks_data))

    # Bước 3: Cập nhật SQLite trên luồng chính trong một transaction duy nhất
    with session_scope() as db:
        for t, out_dict in zip(tasks_data, published_results):
            if not t.get("found"):
                continue
            res = out_dict.get("res")
            if out_dict.get("error") or not res or not res.get("success"):
                continue
            h = crud.get_post_history_by_id(db, t["pid"])
            if h:
                h.title = t["title"]
                h.raw_html = t["raw_html"]
                h.short_description = t["short_desc"]
                h.regular_price = t["reg_price"]
                h.sale_price = t["sale_price"]
                h.status = "published" if post_status == "publish" else "draft"
                h.wp_post_id = str(res.get("post_id", ""))
                h.wp_post_url = res.get("post_url")
                h.published_at = now_vn()
                h.error_message = None
        db.commit()

    # Bước 4: Trả về kết quả đúng theo thứ tự ban đầu của post_ids
    out: list[BatchItem] = []
    for t, out_dict in zip(tasks_data, published_results):
        pid = t["pid"]
        if not t.get("found"):
            out.append(BatchItem(pid, "?", "?", False, "Không tìm thấy bài"))
            continue
        err = out_dict.get("error")
        res = out_dict.get("res")
        prod_name = t.get("product_name") or "?"
        site_name = t.get("site_name") or "?"
        if err or not res or not res.get("success"):
            error_msg = err or (res.get("error") if res else "Lỗi không xác định")
            out.append(BatchItem(pid, prod_name, site_name, False, error_msg))
        else:
            post_url = res.get("post_url") or ""
            img_warn = res.get("image_warning")
            note = post_url + (f" ⚠️ {img_warn}" if img_warn else "")
            out.append(BatchItem(pid, prod_name, site_name, True, note))

    return out


def schedule_saved_batch(
    post_ids: list[int],
    post_status: str,
    start: datetime,
    post_gap_minutes: int = 0,
    site_gap_minutes: int = 0,
) -> list[BatchItem]:
    """
    Hẹn giờ đăng các bài đã lưu; mỗi (bài, website) là một lịch riêng nên có thể đăng ở giờ khác nhau:
    giờ = start + (thứ tự sản phẩm × post_gap) + (thứ tự website của sản phẩm đó × site_gap).
    Khi đến giờ, lịch cập nhật chính bản ghi trong kho (không tạo bản ghi trùng).
    """
    from datetime import timedelta

    from services import schedules  # tránh vòng import lúc nạp module

    details = [d for d in (get_post(p) for p in post_ids) if d]
    product_index: dict[str, int] = {}
    site_index: dict[str, int] = {}
    out: list[BatchItem] = []
    for d in details:
        pi = product_index.setdefault(d.product_name, len(product_index))
        si = site_index.get(d.product_name, 0)
        site_index[d.product_name] = si + 1
        when = start + timedelta(minutes=pi * max(post_gap_minutes, 0) + si * max(site_gap_minutes, 0))
        art = {
            "title": d.title, "raw_html": d.raw_html, "short_description": d.short_description,
            "product_name": d.product_name, "category_ids": d.category_ids, "tags": d.tags,
            "category_scope": taxonomy_svc.scope_of(d.post_type), "history_id": d.id,
        }
        try:
            schedules.schedule_post(
                {d.site_name: art}, d.existing_image_paths, post_status, d.post_type, when,
                d.regular_price, d.sale_price,
            )
            out.append(BatchItem(d.id, d.product_name, d.site_name, True, "", when))
        except ServiceError as e:
            out.append(BatchItem(d.id, d.product_name, d.site_name, False, e.message))
    return out


def delete_posts_batch(post_ids: list[int]) -> list[BatchItem]:
    """Xoá các bản ghi trong kho (không động tới bài đã đăng trên WordPress)."""
    out: list[BatchItem] = []
    for pid in post_ids:
        d = get_post(pid)
        try:
            delete_post(pid)
            out.append(BatchItem(pid, d.product_name if d else "?", d.site_name if d else "?", True))
        except ServiceError as e:
            out.append(BatchItem(pid, d.product_name if d else "?", d.site_name if d else "?", False, e.message))
    return out
