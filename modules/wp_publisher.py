"""
modules/wp_publisher.py
Đăng bài lên WordPress qua REST API.
Xử lý: thay IMAGE_PLACEHOLDER, tạo post, gắn featured image.
"""
from __future__ import annotations
import logging
import re

import requests
from requests.auth import HTTPBasicAuth

from modules.image_uploader import build_figure_html

logger = logging.getLogger(__name__)


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


def publish_product(
    title: str,
    html_content: str,
    uploaded_images: list[dict],
    site_config: dict,
    status: str = "draft",
    category_ids: list[int] | None = None,
    regular_price: str = "",
) -> dict:
    """
    Đăng sản phẩm lên WooCommerce qua REST API (/wp-json/wc/v3/products).
    Sử dụng trực tiếp client_key và client_secret từ .env.
    """
    final_html = _replace_placeholders(html_content, uploaded_images)

    # Tự động trích xuất bảng thông số kỹ thuật cho short_description
    short_desc = ""
    table_match = re.search(r"(<table>.*?</table>)", final_html, re.DOTALL | re.IGNORECASE)
    if table_match:
        short_desc = table_match.group(1)

    base_url = site_config["url"].rstrip("/")
    auth = HTTPBasicAuth(site_config["client_key"], site_config["client_secret"])
    endpoint = f"{base_url}/wp-json/wc/v3/products"

    payload: dict = {
        "name": title,
        "type": "simple",
        "description": final_html,
        "short_description": short_desc,
        "status": status,
    }

    if regular_price:
        payload["regular_price"] = str(regular_price)

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

    if uploaded_images:
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


def test_connection(site_config: dict) -> bool:
    """
    Kiểm tra kết nối và xác thực với WordPress REST API.
    Thử đọc danh sách posts (không cần quyền cao).

    Returns:
        True nếu kết nối thành công.
    """
    base_url = site_config["url"].rstrip("/")
    auth = _get_wp_auth(site_config)

    # Thử endpoint categories (không cần xác thực)
    try:
        r = requests.get(f"{base_url}/wp-json/wp/v2/categories", timeout=10)
        if r.status_code == 200:
            logger.info(f"✓ Kết nối REST API thành công tới {base_url}")
        else:
            logger.warning(f"REST API trả về HTTP {r.status_code}")
    except Exception as e:
        logger.error(f"✗ Không kết nối được: {e}")
        return False

    # Thử xác thực (nếu có Application Password)
    wp_user = site_config.get("wp_user", "")
    if wp_user:
        try:
            r2 = requests.get(f"{base_url}/wp-json/wp/v2/users/me", auth=auth, timeout=10)
            if r2.status_code == 200:
                user = r2.json()
                logger.info(f"✓ Xác thực thành công! Đăng nhập với: {user.get('name', '?')}")
                return True
            else:
                logger.error(f"✗ Lỗi xác thực Application Password: HTTP {r2.status_code}")
                return False
        except Exception as e:
            logger.error(f"✗ Lỗi xác thực: {e}")
            return False

    logger.info("Chưa cấu hình WP_USER/WP_APP_PASSWORD - chỉ kiểm tra kết nối cơ bản")
    return True


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
