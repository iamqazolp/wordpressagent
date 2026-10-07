"""
services/sites.py — quản lý website WordPress/WooCommerce (cấu hình, watermark, kiểm tra kết nối).

Nghiệp vụ tách khỏi ui/tab_sites.py. Khóa API được mã hóa trong DB (db.crud); các hàm trả về
cấu hình đã giải mã chỉ khi nơi gọi cần (form chỉnh sửa, đăng bài), còn danh sách tổng quan chỉ trả
phần xem trước đã che.
"""
from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from core import wp_client
from db import crud
from db.database import DATA_DIR, project_path, session_scope, to_project_relative
from services.errors import ServiceError

logger = logging.getLogger(__name__)

LOGOS_DIR = DATA_DIR / "logos"
DEFAULT_WM_POSITION = "bottom-right"
DEFAULT_WM_OPACITY = 0.7


@dataclass(frozen=True)
class SiteOverview:
    name: str
    url: str
    client_key_preview: str      # 8 ký tự đầu của Consumer Key ("" nếu chưa có) — không bao giờ trả khóa đầy đủ
    has_wp_credentials: bool
    watermark_path: str          # đường dẫn logo ("" nếu chưa có hoặc file không còn)
    watermark_position: str


@dataclass(frozen=True)
class ConnectionResult:
    wc_ok: bool
    wp_ok: bool
    wp_configured: bool          # người dùng đã nhập WP user + Application Password


def safe_filename(name: str) -> str:
    """Tạo tên file an toàn từ tên website."""
    clean = re.sub(r"[^\w\-.]", "_", name.strip().lower())
    return clean or "site"


def normalize_url(raw_url: str) -> str:
    """Chuẩn hóa URL website: bỏ khoảng trắng, trailing slash, tự động thêm https:// nếu thiếu scheme."""
    url = (raw_url or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def _existing_logo(path: str | None) -> str:
    return str(project_path(path)) if (path and project_path(path).exists()) else ""


def list_site_names() -> list[str]:
    with session_scope() as db:
        return crud.get_site_names(db)


def get_site_configs() -> dict[str, dict]:
    """{tên: cấu hình đã giải mã} — dùng cho đăng bài. Không đưa ra màn hình."""
    with session_scope() as db:
        return crud.get_all_site_configs(db)


def get_site_config(name: str) -> dict | None:
    """Cấu hình đầy đủ (đã giải mã) của một website; None nếu không có."""
    with session_scope() as db:
        site = crud.get_site_by_name(db, name)
        return crud.get_site_config(db, site.id) if site else None


def list_sites_overview() -> list[SiteOverview]:
    with session_scope() as db:
        out: list[SiteOverview] = []
        for site in crud.get_all_sites(db):
            cfg = crud.get_site_config(db, site.id)
            if not cfg:
                continue
            key = cfg.get("client_key") or ""
            out.append(SiteOverview(
                name=site.name,
                url=site.url,
                client_key_preview=key[:8],
                has_wp_credentials=bool(cfg.get("wp_user") and cfg.get("wp_app_password")),
                watermark_path=_existing_logo(cfg.get("watermark_path")),
                watermark_position=cfg.get("watermark_position") or DEFAULT_WM_POSITION,
            ))
        return out


def get_watermark_preview(name: str) -> str | None:
    """Đường dẫn logo watermark hiện có của website (None nếu chưa có / file đã mất)."""
    with session_scope() as db:
        site = crud.get_site_by_name(db, name)
        return _existing_logo(site.watermark_path) or None if site else None


def _store_watermark(site_name: str, source_path: str | None) -> str | None:
    """Sao chép file logo người dùng tải lên vào data/logos; trả đường dẫn mới (None nếu không có file)."""
    if not source_path or not Path(source_path).exists():
        return None
    LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(source_path).suffix.lower() or ".png"
    dest = LOGOS_DIR / f"{safe_filename(site_name)}_watermark{ext}"
    shutil.copy2(source_path, dest)
    logger.info(f"Đã lưu logo watermark cho {site_name} tại {dest}")
    return to_project_relative(dest)


def save_site(
    name: str,
    url: str,
    client_key: str,
    client_secret: str,
    wp_user: str,
    wp_app_password: str,
    watermark_source: str | None,
    watermark_position: str,
    watermark_opacity: float,
    current_name: str | None = None,
) -> tuple[str, bool]:
    """
    Thêm mới (current_name rỗng) hoặc cập nhật website. Trả (tên_đã_lưu, created).
    Raise ServiceError khi dữ liệu sai/trùng tên/không tìm thấy. Chỉ sao chép logo sau khi dữ liệu hợp lệ.
    """
    name = (name or "").strip()
    url = normalize_url(url)
    if not name or not url:
        raise ServiceError("Vui lòng nhập tên website và URL!")

    position = watermark_position or DEFAULT_WM_POSITION
    opacity = float(watermark_opacity or DEFAULT_WM_OPACITY)

    with session_scope() as db:
        if not current_name:
            if crud.get_site_by_name(db, name):
                raise ServiceError(f"Tên website '{name}' đã tồn tại!")
            site = crud.create_site(
                db,
                name=name,
                url=url,
                client_key=client_key,
                client_secret=client_secret,
                wp_user=wp_user,
                wp_app_password=wp_app_password,
                watermark_path=_store_watermark(name, watermark_source) or "",
                watermark_position=position,
                watermark_opacity=opacity,
            )
            if not site:
                raise ServiceError(f"Lỗi khi thêm website {name}")
            return name, True

        site = crud.get_site_by_name(db, current_name)
        if not site:
            raise ServiceError(f"Không tìm thấy website '{current_name}' để cập nhật.")
        if name != current_name and crud.get_site_by_name(db, name):
            raise ServiceError(f"Tên website mới '{name}' đã được sử dụng.")
        fields = {
            "name": name,
            "url": url,
            "client_key": client_key,
            "client_secret": client_secret,
            "wp_user": wp_user,
            "wp_app_password": wp_app_password,
            "watermark_position": position,
            "watermark_opacity": opacity,
        }
        new_logo = _store_watermark(name, watermark_source)
        if new_logo:
            fields["watermark_path"] = new_logo
        if not crud.update_site(db, site.id, **fields):
            raise ServiceError(f"Lỗi khi cập nhật website {name}")
        return name, False


def delete_site(name: str) -> None:
    with session_scope() as db:
        site = crud.get_site_by_name(db, name)
        if not site:
            raise ServiceError(f"Không tìm thấy website '{name}'.")
        if not crud.delete_site(db, site.id):
            raise ServiceError(f"Không thể xóa website '{name}' (có thể đây là website cuối cùng).")


def clear_watermark(name: str) -> None:
    """Xóa logo watermark (cả file vật lý nếu còn) của website."""
    with session_scope() as db:
        site = crud.get_site_by_name(db, name)
        if not site:
            raise ServiceError(f"Không tìm thấy website '{name}'.")
        if site.watermark_path and project_path(site.watermark_path).exists():
            try:
                project_path(site.watermark_path).unlink()
            except Exception as e:
                logger.warning(f"Không thể xóa file watermark cũ: {e}")
        crud.update_site(db, site.id, watermark_path="")


def test_connection(url: str, client_key: str, client_secret: str, wp_user: str = "", wp_password: str = "") -> ConnectionResult:
    """Kiểm tra kết nối bằng thông tin đang nhập (chưa cần lưu)."""
    url = normalize_url(url)
    if not url or not client_key or not client_secret:
        raise ServiceError("Vui lòng điền đủ URL, WooCommerce Client Key và Client Secret trước khi kiểm tra!")
    res = wp_client.test_connection({
        "url": url,
        "client_key": client_key,
        "client_secret": client_secret,
        "wp_user": wp_user,
        "wp_app_password": wp_password,
    })
    return ConnectionResult(
        wc_ok=bool(res.get("wc_ok", False)),
        wp_ok=bool(res.get("wp_ok", False)),
        wp_configured=bool(wp_user and wp_password),
    )


test_connection.__test__ = False  # tên bắt đầu bằng "test_" nhưng không phải test pytest
