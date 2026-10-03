"""
services/images.py — xử lý ảnh sản phẩm theo cấu hình từng website (nén WebP, watermark, tách nền).

Phần xử lý ảnh thật nằm ở core/image_processor.py; ở đây chỉ chọn tùy chọn theo website và gom kết quả.
"""
from __future__ import annotations

import logging

from core.image_processor import process_image_batch
from services import sites as site_service

logger = logging.getLogger(__name__)

_DEFAULT_POSITION = "bottom-right"
_DEFAULT_OPACITY = 0.7


def _watermark_options(site_cfg: dict | None) -> dict:
    cfg = site_cfg or {}
    return {
        "watermark_path": cfg.get("watermark_path") or None,
        "watermark_position": cfg.get("watermark_position") or _DEFAULT_POSITION,
        "watermark_opacity": cfg.get("watermark_opacity") or _DEFAULT_OPACITY,
    }


def optimize_for_site(image_paths: list[str], site_name: str, remove_bg: bool = False) -> list[str]:
    """
    Tối ưu (WebP ≤1200px, q85) và đóng watermark của website cho bộ ảnh; trả đường dẫn ảnh đã xử lý.
    Lỗi xử lý → trả lại ảnh gốc (không chặn việc lưu bài).
    """
    if not image_paths:
        return []
    try:
        results = process_image_batch(
            image_paths,
            options={
                "max_width": 1200,
                "max_height": 1200,
                "format": "WEBP",
                "quality": 85,
                "remove_bg": remove_bg,
                **_watermark_options(site_service.get_site_config(site_name)),
            },
        )
        return [r["output_path"] for r in results if r.get("output_path")] or list(image_paths)
    except Exception as e:
        logger.warning(f"Lỗi tối ưu ảnh cho {site_name}: {e}")
        return list(image_paths)


def preview_processed(
    image_paths: list[str],
    site_name: str | None,
    optimize: bool,
    watermark: bool,
    remove_bg: bool,
) -> tuple[list[str], list[dict]]:
    """Xử lý thử bộ ảnh để xem trước. Trả (đường_dẫn_ảnh_đã_xử_lý, danh_sách_kết_quả_từng_ảnh)."""
    wm = _watermark_options(site_service.get_site_config(site_name) if (watermark and site_name) else None)
    if not (watermark and site_name):
        wm["watermark_path"] = None
    results = process_image_batch(
        image_paths,
        options={
            "max_width": 1200 if optimize else 9999,
            "max_height": 1200 if optimize else 9999,
            "format": "WEBP" if optimize else "JPEG",
            "quality": 85,
            "remove_bg": remove_bg,
            **wm,
        },
    )
    return [r["output_path"] for r in results if r.get("output_path")], results
