"""
core/wp_client.py
Đăng bài lên WordPress qua REST API và upload ảnh.
"""
from __future__ import annotations
import logging
import mimetypes
import os
import re
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth
from tenacity import retry, stop_after_attempt, wait_fixed

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


def _get_wp_auth(site_config: dict) -> HTTPBasicAuth:
    """
    Trả về xác thực phù hợp để gọi WordPress REST API.
    Ưu tiên dùng Application Password (wp_user + wp_app_password) nếu có,
    fallback về WooCommerce key (hoạt động cho một số endpoint).
    """
    wp_user = site_config.get("wp_user", "")
    wp_pass = site_config.get("wp_app_password", "")
    if wp_user and wp_pass:
        return HTTPBasicAuth(wp_user, wp_pass)
    # Fallback: WooCommerce key (chỉ dùng cho WooCommerce API, không đăng WP post)
    return HTTPBasicAuth(site_config["client_key"], site_config["client_secret"])


def _clean_price(price_str: str) -> str:
    """Làm sạch định dạng giá tiền (loại bỏ dấu chấm, phẩy, chữ đ/VND) để chuẩn định dạng WooCommerce."""
    if not price_str:
        return ""
    # Giữ lại chỉ các chữ số
    cleaned = re.sub(r"[^\d]", "", str(price_str))
    return cleaned.strip()


@retry(stop=stop_after_attempt(2), wait=wait_fixed(3), reraise=True)
def publish_product(
    title: str,
    html_content: str,
    uploaded_images: list[dict],
    site_config: dict,
    status: str = "draft",
    category_ids: list[int] | None = None,
    regular_price: str = "",
    sale_price: str = "",
    short_description: str = "",
) -> dict:
    """
    Đăng sản phẩm lên WooCommerce qua REST API (/wp-json/wc/v3/products).
    Sử dụng trực tiếp client_key và client_secret từ .env.
    """
    final_html = _replace_placeholders(html_content, uploaded_images)

    # Tự động trích xuất bảng thông số kỹ thuật cho short_description nếu chưa truyền vào
    if not short_description:
        table_match = re.search(r"(<table\b.*?>.*?</table>)", final_html, re.DOTALL | re.IGNORECASE)
        if table_match:
            short_description = table_match.group(1)

    base_url = site_config["url"].rstrip("/")
    auth = HTTPBasicAuth(site_config["client_key"], site_config["client_secret"])
    endpoint = f"{base_url}/wp-json/wc/v3/products"

    payload: dict = {
        "name": title,
        "type": "simple",
        "description": final_html,
        "short_description": short_description,
        "status": status,
    }

    clean_reg = _clean_price(regular_price)
    if clean_reg:
        payload["regular_price"] = clean_reg

    clean_sale = _clean_price(sale_price)
    if clean_sale:
        payload["sale_price"] = clean_sale

    if category_ids:
        payload["categories"] = [{"id": cid} for cid in category_ids]

    if uploaded_images:
        images_payload = []
        for img in uploaded_images:
            if "id" in img and img["id"]:
                images_payload.append({"id": img["id"]})
            elif "url" in img and img["url"]:
                images_payload.append({"src": img["url"]})
        if images_payload:
            payload["images"] = images_payload

    logger.info(f"Đang tạo sản phẩm WooCommerce tại {base_url} (status={status})...")

    try:
        response = requests.post(endpoint, auth=auth, json=payload, timeout=30)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.error(f"Lỗi HTTP khi tạo sản phẩm: {e}\n{response.text[:500]}")
        raise
    except Exception as e:
        logger.error(f"Lỗi kết nối khi tạo sản phẩm: {e}")
        raise

    data = response.json()
    product_id = data["id"]
    product_url = data.get("permalink", f"{base_url}/?post_type=product&p={product_id}")
    edit_url = f"{base_url}/wp-admin/post.php?post={product_id}&action=edit"

    logger.info(f"✓ Đăng sản phẩm thành công! ID={product_id} | URL={product_url}")

    return {
        "post_id": product_id,
        "post_url": product_url,
        "edit_url": edit_url,
        "status": status,
        "type": "product",
    }


@retry(stop=stop_after_attempt(2), wait=wait_fixed(3), reraise=True)
def publish_post(
    title: str,
    html_content: str,
    uploaded_images: list[dict],
    site_config: dict,
    status: str = "draft",
    category_ids: list[int] | None = None,
) -> dict:
    """
    Đăng bài viết thông thường (Blog Post) lên WordPress qua REST API (/wp-json/wp/v2/posts).
    Cần WordPress Application Password (WP_USER + WP_APP_PASSWORD).
    """
    final_html = _replace_placeholders(html_content, uploaded_images)

    base_url = site_config["url"].rstrip("/")
    auth = _get_wp_auth(site_config)
    endpoint = f"{base_url}/wp-json/wp/v2/posts"

    payload: dict = {
        "title":   title,
        "content": final_html,
        "status":  status,
    }

    if category_ids:
        payload["categories"] = category_ids

    if uploaded_images and uploaded_images[0].get('id'):
        payload["featured_media"] = uploaded_images[0]["id"]

    logger.info(f"Đang đăng bài blog lên {base_url} (status={status})...")

    try:
        response = requests.post(
            endpoint,
            auth=auth,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.error(f"Lỗi HTTP khi đăng bài: {e}\n{response.text[:500]}")
        raise
    except Exception as e:
        logger.error(f"Lỗi kết nối khi đăng bài: {e}")
        raise

    data = response.json()
    post_id  = data["id"]
    post_url = data["link"]
    edit_url = f"{base_url}/wp-admin/post.php?post={post_id}&action=edit"

    logger.info(f"✓ Đăng bài thành công! ID={post_id} | URL={post_url}")

    return {
        "post_id":  post_id,
        "post_url": post_url,
        "edit_url": edit_url,
        "status":   status,
        "type": "post",
    }


def _replace_placeholders(html_content: str, images: list[dict]) -> str:
    """
    Thay [IMAGE_PLACEHOLDER_N] bằng thẻ <figure> HTML thực tế.

    Args:
        html_content: HTML chứa placeholder.
        images:       Danh sách ảnh đã upload.

    Returns:
        HTML đã thay thế xong.
    """
    if not images:
        # Xóa tất cả placeholder nếu không có ảnh
        html_content = re.sub(r"\[IMAGE_PLACEHOLDER_\d+\]", "", html_content)
        return html_content

    def replace_one(match: re.Match) -> str:
        # Lấy số N trong [IMAGE_PLACEHOLDER_N]
        n = int(match.group(1)) - 1  # convert sang 0-based
        if 0 <= n < len(images):
            return build_figure_html(images[n])
        # Nếu N vượt quá số ảnh → dùng ảnh cuối
        return build_figure_html(images[-1])

    return re.sub(r"\[IMAGE_PLACEHOLDER_(\d+)\]", replace_one, html_content)


def test_connection(site_config: dict) -> dict:
    """
    Kiểm tra kết nối và xác thực với WordPress REST API.
    Thử đọc danh sách posts và products để kiểm tra cả wp và wc API.

    Returns:
        {'wp_ok': bool, 'wc_ok': bool, 'wp_version': str, 'wc_version': str, 'message': str}
    """
    base_url = site_config["url"].rstrip("/")
    auth = _get_wp_auth(site_config)
    result = {'wp_ok': False, 'wc_ok': False, 'wp_version': '', 'wc_version': '', 'message': ''}

    # Thử endpoint categories (kiểm tra WP)
    try:
        r = requests.get(f"{base_url}/wp-json/wp/v2/categories", timeout=10)
        if r.status_code == 200:
            logger.info(f"✓ Kết nối WP REST API thành công tới {base_url}")
            result['wp_ok'] = True
            # Thử lấy version nếu có auth
            wp_user = site_config.get("wp_user", "")
            if wp_user:
                r2 = requests.get(f"{base_url}/wp-json/wp/v2/users/me", auth=auth, timeout=10)
                if r2.status_code == 200:
                    logger.info("✓ Xác thực WP Application Password thành công!")
        else:
            logger.warning(f"WP REST API trả về HTTP {r.status_code}")
            result['message'] += f"WP HTTP {r.status_code}. "
    except Exception as e:
        logger.error(f"✗ Không kết nối được WP: {e}")
        result['message'] += f"Lỗi WP: {e}. "

    # Thử endpoint WooCommerce
    wc_auth = HTTPBasicAuth(site_config["client_key"], site_config["client_secret"])
    try:
        r_wc = requests.get(f"{base_url}/wp-json/wc/v3/", auth=wc_auth, timeout=10)
        if r_wc.status_code == 200:
            data = r_wc.json()
            result['wc_ok'] = True
            result['wc_version'] = data.get('version', '')
            logger.info(f"✓ Kết nối WC REST API thành công. Version: {result['wc_version']}")
        else:
            logger.warning(f"WC REST API trả về HTTP {r_wc.status_code}")
            result['message'] += f"WC HTTP {r_wc.status_code}. "
    except Exception as e:
        logger.error(f"✗ Không kết nối được WC: {e}")
        result['message'] += f"Lỗi WC: {e}. "

    if result['wp_ok'] and result['wc_ok']:
        result['message'] = "Kết nối thành công cả WP và WC API."
    elif not result['message']:
        result['message'] = "Kết nối không thành công."

    return result


def get_categories(site_config: dict) -> list[dict]:
    """
    Lấy danh sách categories từ WordPress.

    Returns:
        List[{"id": int, "name": str}]
    """
    base_url = site_config["url"].rstrip("/")
    auth = _get_wp_auth(site_config)
    endpoint = f"{base_url}/wp-json/wp/v2/categories?per_page=100"

    try:
        response = requests.get(endpoint, auth=auth, timeout=10)
        response.raise_for_status()
        cats = response.json()
        return [{"id": c["id"], "name": c["name"]} for c in cats]
    except Exception as e:
        logger.warning(f"Không lấy được danh sách category: {e}")
        return []
