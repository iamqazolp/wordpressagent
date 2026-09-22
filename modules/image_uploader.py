"""
modules/image_uploader.py
Upload ảnh lên WordPress Media Library qua REST API.
"""
import logging
import mimetypes
import os
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)


def upload_images(image_paths: list[str], site_config: dict) -> list[dict]:
    """
    Upload nhiều ảnh lên WordPress Media Library.

    Args:
        image_paths:  Danh sách đường dẫn file ảnh trên máy.
        site_config:  {"url": str, "client_key": str, "client_secret": str}

    Returns:
        List[{"id": int, "url": str, "filename": str}]
        - id:       WordPress attachment ID (dùng để gắn vào post)
        - url:      URL công khai của ảnh sau khi upload
        - filename: Tên file gốc
    """
    base_url = site_config["url"].rstrip("/")
    # Ưu tiên Application Password để upload media
    wp_user = site_config.get("wp_user", "")
    wp_pass = site_config.get("wp_app_password", "")
    if wp_user and wp_pass:
        auth = HTTPBasicAuth(wp_user, wp_pass)
    else:
        auth = HTTPBasicAuth(site_config["client_key"], site_config["client_secret"])
    endpoint = f"{base_url}/wp-json/wp/v2/media"

    uploaded = []

    for path_str in image_paths:
        path = Path(path_str)
        if not path.exists():
            logger.warning(f"File không tồn tại: {path_str}")
            continue

        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type:
            mime_type = "image/jpeg"

        logger.info(f"Đang upload: {path.name}")

        try:
            with open(path, "rb") as f:
                response = requests.post(
                    endpoint,
                    auth=auth,
                    headers={
                        "Content-Disposition": f'attachment; filename="{path.name}"',
                        "Content-Type": mime_type,
                    },
                    data=f,
                    timeout=60,
                )

            if response.status_code in (200, 201):
                data = response.json()
                result = {
                    "id": data["id"],
                    "url": data["source_url"],
                    "filename": path.name,
                }
                uploaded.append(result)
                logger.info(f"✓ Upload thành công: {path.name} → {result['url']}")
            else:
                logger.error(
                    f"✗ Lỗi upload {path.name}: "
                    f"HTTP {response.status_code} - {response.text[:200]}"
                )

        except Exception as e:
            logger.error(f"✗ Lỗi upload {path.name}: {e}")

    return uploaded


def build_figure_html(image_data: dict, caption: str = "") -> str:
    """
    Tạo HTML <figure> chuẩn WordPress cho một ảnh.

    Args:
        image_data: {"id": int, "url": str, "filename": str}
        caption:    Chú thích ảnh (có thể để trống)

    Returns:
        Chuỗi HTML <figure>...</figure>
    """
    img_id  = image_data["id"]
    img_url = image_data["url"]
    caption_html = (
        f'\n<figcaption class="wp-caption-text">{caption}</figcaption>'
        if caption
        else ""
    )
    return (
        f'<figure id="attachment_{img_id}" '
        f'style="width: 800px" class="wp-caption aligncenter">'
        f'<a href="{img_url}">'
        f'<img decoding="async" class="wp-image-{img_id} size-full" '
        f'src="{img_url}" alt="{caption}" width="800" height="600" />'
        f"</a>"
        f"{caption_html}"
        f"</figure>"
    )
