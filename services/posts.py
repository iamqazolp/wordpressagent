"""
services/posts.py — kho bài viết (PostHistory): liệt kê, xem, sửa, xóa, đăng bài đã lưu.

Nghiệp vụ tách khỏi ui/tab_history.py. Trả dataclass thuần (không ORM). Việc đăng một bài dùng chung
core.pipeline.publish_one với luồng "Tạo & Đăng bài" để hành vi (ảnh, danh mục, tag, cảnh báo) giống hệt nhau.
"""
from __future__ import annotations

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
    out: list[BatchItem] = []
    for pid in post_ids:
        d = get_post(pid)
        if not d:
            out.append(BatchItem(pid, "?", "?", False, "Không tìm thấy bài"))
            continue
        try:
            res = publish_saved_post(
                pid, d.title, d.short_description, d.regular_price, d.sale_price, d.raw_html,
                d.post_type, post_status,
            )
            note = res.post_url + (f" ⚠️ {res.image_warning}" if res.image_warning else "")
            out.append(BatchItem(pid, d.product_name, d.site_name, True, note))
        except (ServiceError, PublishError) as e:
            out.append(BatchItem(pid, d.product_name, d.site_name, False, e.message))
        except Exception as e:
            out.append(BatchItem(pid, d.product_name, d.site_name, False, str(e)))
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
