"""
services/sync.py — đồng bộ với WordPress: phát hiện bài trùng, xem danh sách trên website (chỉ đọc),
làm mới trạng thái bài đã đăng, liên kết bài WP có sẵn và đưa bài vào thùng rác.

An toàn:
  * Đọc (list/search/get) không bao giờ ghi lên WordPress.
  * Xóa CHỈ là chuyển vào thùng rác (core.wp_client.trash_item không có tuỳ chọn xóa vĩnh viễn) và
    luôn cần `confirm=True` từ người gọi.
  * Cập nhật bài (PUT) nằm ở services/posts.publish_saved_post(update_existing=True).
Trả dataclass thuần; không import UI.
"""
from __future__ import annotations

import difflib
import logging
import unicodedata
from dataclasses import dataclass

from core import wp_client
from core.timeutil import utc_iso_to_vn
from db import crud
from db.database import session_scope
from db.models import PostHistory
from services.errors import ServiceError
from services.taxonomy import scope_of

logger = logging.getLogger(__name__)

DUPLICATE_THRESHOLD = 0.72

# Trạng thái WordPress -> trạng thái lưu trong kho bài (PostHistory.status)
_REMOTE_TO_LOCAL = {
    "publish": "published",
    "draft": "draft",
    "pending": "draft",
    "private": "draft",
    "future": "draft",
    "trash": "trashed",
}
SYNCABLE_STATUSES = ("published", "draft")


@dataclass(frozen=True)
class RemoteItem:
    id: int
    title: str
    status: str                  # trạng thái gốc của WordPress (publish/draft/trash...)
    url: str
    modified: str                # giờ GMT+7 đã định dạng ('-' nếu không có)
    type: str                    # 'product' | 'post'
    local_post_id: int | None    # id trong kho bài nếu bài này do app đăng/đã liên kết


@dataclass(frozen=True)
class RemotePage:
    items: list[RemoteItem]
    total: int
    page: int
    per_page: int


@dataclass(frozen=True)
class DuplicateMatch:
    wp_id: int
    title: str
    status: str
    url: str
    similarity: float            # 0..1
    local_post_id: int | None


@dataclass(frozen=True)
class DuplicateResult:
    site_name: str
    matches: list[DuplicateMatch]
    error: str = ""              # có lỗi thì không kết luận được (không chặn việc đăng)


@dataclass(frozen=True)
class StatusChange:
    post_id: int
    old: str
    new: str


@dataclass(frozen=True)
class RefreshReport:
    checked: int
    changes: list[StatusChange]
    errors: list[str]


# ── Tiện ích thuần ───────────────────────────────────────────────────────────

def _fold(text: str) -> str:
    """Hạ chữ thường + bỏ dấu + gộp khoảng trắng để so khớp tên sản phẩm tiếng Việt."""
    t = unicodedata.normalize("NFKD", (text or "").replace("đ", "d").replace("Đ", "D"))
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    return " ".join("".join(c if c.isalnum() else " " for c in t).split())


def similarity(a: str, b: str) -> float:
    """Độ giống 0..1. Chuỗi này chứa chuỗi kia (sau khi chuẩn hóa) coi như ≥ 0.9."""
    fa, fb = _fold(a), _fold(b)
    if not fa or not fb:
        return 0.0
    ratio = difflib.SequenceMatcher(None, fa, fb).ratio()
    if fa in fb or fb in fa:
        ratio = max(ratio, 0.9)
    return ratio


def _modified_vn(item: dict) -> str:
    """Giờ sửa cuối theo GMT+7. Ưu tiên trường UTC (*_gmt) vì giờ 'local' của WP phụ thuộc cài đặt múi giờ của site."""
    return utc_iso_to_vn(item.get("modified_gmt")) if item.get("modified_gmt") else (item.get("modified") or "-")


def edit_url(site_url: str, wp_id: int | str) -> str:
    return f"{site_url.rstrip('/')}/wp-admin/post.php?post={wp_id}&action=edit"


def local_status_for(remote_status: str | None) -> str:
    """Trạng thái kho bài tương ứng với trạng thái WordPress (None = bài không còn trên WP)."""
    if remote_status is None:
        return "missing"
    return _REMOTE_TO_LOCAL.get(remote_status, "draft")


# ── Truy cập site ────────────────────────────────────────────────────────────

def _site_and_config(db, site_name: str):
    site = crud.get_site_by_name(db, site_name)
    if not site:
        raise ServiceError(f"Không tìm thấy website '{site_name}'.")
    cfg = crud.get_site_config(db, site.id)
    if not cfg:
        raise ServiceError(f"Không đọc được cấu hình của website '{site_name}'.")
    return site, cfg


def _local_ids_by_wp_id(db, site_id: int, wp_ids: list) -> dict[str, int]:
    if not wp_ids:
        return {}
    rows = (
        db.query(PostHistory.id, PostHistory.wp_post_id)
        .filter(PostHistory.site_id == site_id, PostHistory.wp_post_id.in_([str(i) for i in wp_ids]))
        .order_by(PostHistory.id)
        .all()
    )
    out: dict[str, int] = {}
    for pid, wid in rows:
        out[str(wid)] = pid  # nếu có nhiều bản ghi trùng id WP, lấy bản mới nhất
    return out


# ── Danh sách trên website (chỉ đọc) ─────────────────────────────────────────

def list_remote(site_name: str, post_type: str, status: str = "any", search: str = "", page: int = 1, per_page: int = 20) -> RemotePage:
    """Sản phẩm/bài đang có trên website. Raise ServiceError nếu không đọc được."""
    scope = scope_of(post_type)
    with session_scope() as db:
        site, cfg = _site_and_config(db, site_name)
        try:
            items, total = wp_client.list_items(cfg, scope, page=page, per_page=per_page, status=status, search=search.strip())
        except Exception as e:
            logger.exception("Không đọc được danh sách từ WordPress")
            raise ServiceError(f"Không đọc được danh sách từ {site_name}: {e}")
        local = _local_ids_by_wp_id(db, site.id, [i["id"] for i in items])
        return RemotePage(
            items=[
                RemoteItem(
                    id=i["id"], title=i["title"], status=i["status"], url=i["url"], type=i["type"],
                    modified=_modified_vn(i), local_post_id=local.get(str(i["id"])),
                )
                for i in items
            ],
            total=total, page=page, per_page=per_page,
        )


# ── Phát hiện bài trùng ──────────────────────────────────────────────────────

def find_duplicates(site_name: str, name: str, post_type: str, threshold: float = DUPLICATE_THRESHOLD, limit: int = 5) -> list[DuplicateMatch]:
    """
    Tìm sản phẩm/bài đã có trên website có tên giống `name` (không tính bài đã vào thùng rác).
    Raise ServiceError khi không đọc được website — nơi gọi nên coi là "không kiểm tra được", không chặn đăng.
    """
    if not (name or "").strip():
        return []
    scope = scope_of(post_type)
    with session_scope() as db:
        site, cfg = _site_and_config(db, site_name)
        try:
            items, _ = wp_client.list_items(cfg, scope, page=1, per_page=20, status="any", search=name.strip())
        except Exception as e:
            logger.exception("Không kiểm tra được bài trùng")
            raise ServiceError(f"Không kiểm tra được bài trùng trên {site_name}: {e}")
        local = _local_ids_by_wp_id(db, site.id, [i["id"] for i in items])
    matches = []
    for it in items:
        if it["status"] == "trash":
            continue
        score = similarity(name, it["title"])
        if score >= threshold:
            matches.append(DuplicateMatch(
                wp_id=it["id"], title=it["title"], status=it["status"], url=it["url"],
                similarity=round(score, 2), local_post_id=local.get(str(it["id"])),
            ))
    matches.sort(key=lambda m: m.similarity, reverse=True)
    return matches[:limit]


def check_articles(articles: dict, post_type: str) -> list[DuplicateResult]:
    """Kiểm tra trùng cho từng website của bài đang soạn (articles_state). Không bao giờ raise."""
    results = []
    for site_name, art in (articles or {}).items():
        name = art.get("product_name") or art.get("title") or ""
        try:
            results.append(DuplicateResult(site_name, find_duplicates(site_name, name, post_type)))
        except ServiceError as e:
            results.append(DuplicateResult(site_name, [], error=str(e)))
        except Exception as e:  # noqa: BLE001 — phòng thủ: kiểm tra trùng không được làm hỏng luồng chính
            logger.exception("Lỗi không mong đợi khi kiểm tra trùng")
            results.append(DuplicateResult(site_name, [], error=str(e)))
    return results


def check_saved_post(post_id: int) -> DuplicateResult:
    """Kiểm tra trùng cho 1 bài trong kho (bỏ qua chính bài WP mà bài này đã liên kết)."""
    with session_scope() as db:
        h = crud.get_post_history_by_id(db, post_id)
        if not h or not h.site:
            raise ServiceError("Không tìm thấy bài viết.")
        site_name, name, ptype, own_wp = h.site.name, h.product_name or h.title or "", h.post_type, h.wp_post_id
    matches = [m for m in find_duplicates(site_name, name, ptype) if str(m.wp_id) != str(own_wp or "")]
    return DuplicateResult(site_name, matches)


# ── Liên kết / làm mới trạng thái / thùng rác ────────────────────────────────

def link_remote(post_id: int, wp_id: int) -> str:
    """
    Gắn một sản phẩm/bài ĐÃ CÓ trên WordPress vào bài trong kho (để lần sau 'Cập nhật' ghi đè đúng bài đó,
    thay vì đăng thêm bản trùng). Chỉ đọc WordPress; chỉ ghi DB. Trả trạng thái kho bài mới.
    """
    with session_scope() as db:
        h = crud.get_post_history_by_id(db, post_id)
        if not h or not h.site:
            raise ServiceError("Không tìm thấy bài viết.")
        _, cfg = _site_and_config(db, h.site.name)
        try:
            item = wp_client.get_item(cfg, scope_of(h.post_type), wp_id)
        except Exception as e:
            raise ServiceError(f"Không đọc được bài #{wp_id} trên WordPress: {e}")
        if item is None:
            raise ServiceError(f"Không có bài #{wp_id} trên website (loại nội dung: {scope_of(h.post_type)}).")
        h.wp_post_id = str(item["id"])
        h.wp_post_url = item["url"]
        h.status = local_status_for(item["status"])
        db.commit()
        return h.status


def refresh_statuses(site_name: str | None = None) -> RefreshReport:
    """
    Đọc trạng thái hiện tại trên WordPress của các bài đã đăng từ app (draft → publish, vào thùng rác, bị xóa...)
    và cập nhật kho bài. Chỉ đọc WordPress. Lỗi từng bài được gom lại, không dừng cả lượt.
    """
    changes: list[StatusChange] = []
    errors: list[str] = []
    checked = 0
    with session_scope() as db:
        q = db.query(PostHistory).filter(PostHistory.wp_post_id.isnot(None), PostHistory.wp_post_id != "",
                                         PostHistory.status.in_(SYNCABLE_STATUSES))
        if site_name:
            site = crud.get_site_by_name(db, site_name)
            if not site:
                raise ServiceError(f"Không tìm thấy website '{site_name}'.")
            q = q.filter(PostHistory.site_id == site.id)
        configs: dict[int, dict | None] = {}
        for h in q.order_by(PostHistory.id).all():
            if h.site_id not in configs:
                configs[h.site_id] = crud.get_site_config(db, h.site_id)
            cfg = configs[h.site_id]
            if not cfg:
                errors.append(f"#{h.id}: thiếu cấu hình website")
                continue
            checked += 1
            try:
                item = wp_client.get_item(cfg, scope_of(h.post_type), h.wp_post_id)
            except Exception as e:
                errors.append(f"#{h.id}: {e}")
                continue
            new = local_status_for(item["status"] if item else None)
            if item and item["url"]:
                h.wp_post_url = item["url"]
            if new != h.status:
                changes.append(StatusChange(h.id, h.status, new))
                h.status = new
        db.commit()
    return RefreshReport(checked, changes, errors)


def trash_post(post_id: int, confirm: bool) -> str:
    """
    Đưa bài (đã đăng lên WordPress) vào THÙNG RÁC. Cần confirm=True. Không xóa vĩnh viễn, không xóa bản ghi trong
    kho bài (xóa bản ghi là thao tác riêng của tab Kho bài). Trả thông điệp kết quả.
    """
    if not confirm:
        raise ServiceError("Cần tick ô xác nhận trước khi chuyển bài vào thùng rác WordPress.")
    with session_scope() as db:
        h = crud.get_post_history_by_id(db, post_id)
        if not h or not h.site:
            raise ServiceError("Không tìm thấy bài viết.")
        if not h.wp_post_id:
            raise ServiceError("Bài này chưa được đăng lên WordPress (không có ID bài WP) nên không có gì để xóa.")
        _, cfg = _site_and_config(db, h.site.name)
        try:
            wp_client.trash_item(cfg, scope_of(h.post_type), h.wp_post_id)
        except Exception as e:
            logger.exception("Lỗi chuyển bài vào thùng rác")
            raise ServiceError(f"WordPress không chấp nhận: {e}")
        h.status = "trashed"
        db.commit()
        return f"Đã chuyển bài WP #{h.wp_post_id} trên {h.site.name} vào thùng rác (khôi phục được trong wp-admin)."
