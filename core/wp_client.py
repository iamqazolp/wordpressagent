"""
core/wp_client.py
Đăng bài lên WordPress qua REST API và upload ảnh.
"""
from __future__ import annotations
from datetime import datetime
import concurrent.futures
import logging
import mimetypes
import re
import shutil
import tempfile
import threading
import unicodedata
from pathlib import Path

import inspect
import requests
from requests.auth import HTTPBasicAuth
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

from core.image_processor import process_single_image, DEFAULT_PROCESSED_DIR

logger = logging.getLogger(__name__)

_ORIG_GET = requests.get
_ORIG_POST = requests.post
_ORIG_PUT = getattr(requests, "put", None)
_ORIG_DELETE = getattr(requests, "delete", None)

_session: requests.Session | None = None
_session_lock = threading.Lock()


def get_session() -> requests.Session:
    """
    Trả về requests.Session dùng chung với trust_env=False (bỏ qua tra cứu WPAD proxy chậm trên Windows)
    và kích hoạt HTTP Keep-Alive.
    """
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                s = requests.Session()
                s.trust_env = False
                adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20)
                s.mount("http://", adapter)
                s.mount("https://", adapter)
                _session = s
    return _session


def _req_callers():
    s = get_session()
    s_get = requests.get if requests.get is not _ORIG_GET else s.get
    s_post = requests.post if requests.post is not _ORIG_POST else s.post
    s_put = requests.put if getattr(requests, "put", None) is not _ORIG_PUT else s.put
    s_delete = requests.delete if getattr(requests, "delete", None) is not _ORIG_DELETE else s.delete
    return s_get, s_post, s_put, s_delete


def _safe_call(func, *args, **kwargs):
    """Gọi HTTP callable, lọc bỏ kwargs mà func mock trong test không nhận (vd: mock fake_post không có params)."""
    try:
        sig = inspect.signature(func)
        has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if not has_varkw:
            kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
    except (ValueError, TypeError):
        pass
    return func(*args, **kwargs)


def _wc_params(site_config: dict, params: dict | None = None) -> dict:
    """Truyền consumer_key và consumer_secret qua query params cho WooCommerce REST API."""
    p = dict(params or {})
    if site_config.get("client_key") and site_config.get("client_secret"):
        p["consumer_key"] = site_config["client_key"]
        p["consumer_secret"] = site_config["client_secret"]
    return p


def _should_retry_http(exception: BaseException) -> bool:
    if getattr(exception, "_no_retry", False):
        return False
    if isinstance(exception, ValueError):
        return False
    if isinstance(exception, requests.exceptions.HTTPError):
        if exception.response is not None and exception.response.status_code in (401, 403, 404):
            return False
    return True



def _mark_create_unsafe_to_retry(exc: BaseException) -> None:
    """
    Lệnh POST tạo mới không idempotent: hết giờ đọc / lỗi 5xx có thể xảy ra SAU KHI WordPress đã tạo bài,
    gửi lại sẽ sinh bài trùng. Chỉ thử lại khi chắc chắn yêu cầu chưa tới máy chủ (không kết nối được).
    """
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return
    if isinstance(exc, requests.exceptions.ConnectionError) and not isinstance(exc, requests.exceptions.ReadTimeout):
        return
    try:
        exc._no_retry = True
    except AttributeError:
        pass


def ascii_filename(name: str) -> str:
    """
    Chuyển tên file về ASCII an toàn cho header HTTP (Content-Disposition chỉ nhận latin-1).
    'Bơm dầu thuỷ lực (1)_optimized.webp' -> 'bom-dau-thuy-luc-1-optimized.webp'
    """
    p = Path(name)
    stem = unicodedata.normalize("NFD", p.stem.replace("đ", "d").replace("Đ", "D"))
    stem = "".join(c for c in stem if unicodedata.category(c) != "Mn")
    stem = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").lower() or "image"
    ext = re.sub(r"[^A-Za-z0-9.]", "", p.suffix).lower() or ".jpg"
    return f"{stem}{ext}"


def describe_upload_error(response) -> str:
    """Giải thích lỗi upload ảnh bằng tiếng Việt, kèm mã HTTP và đoạn phản hồi của WordPress."""
    code = response.status_code
    hints = {
        401: "sai Username/Application Password (tạo lại ở WP Admin → Users → Profile → Application Passwords)",
        403: "tài khoản không có quyền tải ảnh, hoặc plugin bảo mật/hosting đang chặn REST API",
        404: "không tìm thấy /wp-json (kiểm tra URL site, hoặc permalink đang là 'Plain')",
        413: "ảnh quá nặng so với giới hạn upload của hosting",
        415: "WordPress không nhận định dạng ảnh này",
        500: "lỗi phía WordPress/hosting (thường do thiếu RAM hoặc thư mục uploads không ghi được)",
    }
    detail = ""
    try:
        detail = str(response.json().get("message", ""))[:150]
    except Exception:
        detail = (response.text or "")[:100].strip()
    hint = hints.get(code, "")
    return f"HTTP {code}" + (f" – {hint}" if hint else "") + (f" [{detail}]" if detail else "")


def check_wp_credentials(site_config: dict, timeout: int = 10) -> str | None:
    """
    Kiểm tra nhanh WordPress profile (Username + Application Password) của một website.
    Trả None nếu hợp lệ, ngược lại là câu giải thích tiếng Việt (dùng để cảnh báo người dùng trước khi tải ảnh).
    """
    user = site_config.get("wp_user", "")
    pwd = site_config.get("wp_app_password", "")
    if not (user and pwd):
        return "chưa điền WordPress Username & Application Password ở tab Quản Lý Website"
    url = site_config["url"].rstrip("/") + "/wp-json/wp/v2/users/me"
    try:
        if requests.get is not _ORIG_GET:
            r = requests.get(url, auth=HTTPBasicAuth(user, pwd), timeout=timeout)
        else:
            r = get_session().get(url, auth=HTTPBasicAuth(user, pwd), timeout=timeout)
    except Exception as e:
        return f"không kết nối được website ({type(e).__name__})"
    if r.status_code == 200:
        return None
    return f"WordPress profile không hợp lệ: {describe_upload_error(r)}"


def upload_images(
    image_paths: list[str],
    site_config: dict,
    optimize: bool = True,
    remove_bg: bool = False,
    apply_watermark: bool = True,
    errors: list[str] | None = None,
) -> list[dict]:
    """
    Upload nhiều ảnh lên WordPress Media Library (Tự động tối ưu WebP & Watermark ở Phase 3).

    Args:
        image_paths:  Danh sách đường dẫn file ảnh trên máy.
        site_config:  {"url": str, "client_key": str, "client_secret": str, "watermark_path": ...}
        optimize:     Có nén WebP và đóng watermark hay không.
        apply_watermark: Có đóng logo watermark của website hay không (chỉ có tác dụng khi optimize=True).
        remove_bg:    Có chạy thuật toán tách nền rembg hay không.

    Returns:
        List[{"id": int, "url": str, "filename": str}]
        - id:       WordPress attachment ID (dùng để gắn vào post)
        - url:      URL công khai của ảnh sau khi upload
        - filename: Tên file gốc
    """
    if not image_paths:
        return []

    errors = errors if errors is not None else []
    errors_lock = threading.Lock()
    base_url = site_config["url"].rstrip("/")
    # Ưu tiên Application Password để upload media
    wp_user = site_config.get("wp_user", "")
    wp_pass = site_config.get("wp_app_password", "")
    if wp_user and wp_pass:
        auth = HTTPBasicAuth(wp_user, wp_pass)
    else:
        auth = HTTPBasicAuth(site_config["client_key"], site_config["client_secret"])
    endpoint = f"{base_url}/wp-json/wp/v2/media"

    session = get_session()
    results: list[dict | None] = [None] * len(image_paths)

    def _upload_single(idx: int, path_str: str) -> None:
        # Thư mục riêng cho từng ảnh: nhiều site (mỗi site một logo) xử lý cùng ảnh song song không ghi đè
        # file của nhau (trên Windows ghi trùng file còn lỗi PermissionError); tên file trên WP vẫn giữ nguyên.
        work_dir = None
        if optimize:
            DEFAULT_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
            work_dir = Path(tempfile.mkdtemp(prefix="upload_", dir=DEFAULT_PROCESSED_DIR))
        try:
            _upload_one(idx, path_str, work_dir)
        finally:
            if work_dir:
                shutil.rmtree(work_dir, ignore_errors=True)

    def _upload_one(idx: int, path_str: str, work_dir: Path | None) -> None:
        path = Path(path_str)
        if not path.exists():
            logger.warning(f"File không tồn tại: {path_str}")
            return

        upload_path = path

        # Tối ưu hóa ảnh (WebP + Watermark) nếu bật cờ optimize
        if optimize:
            try:
                proc_res = process_single_image(
                    input_path=path,
                    output_dir=work_dir,
                    options={
                        "max_width": 1200,
                        "max_height": 1200,
                        "format": "WEBP",
                        "quality": 85,
                        "remove_bg": remove_bg,
                        "watermark_path": (site_config.get("watermark_path") or None) if apply_watermark else None,
                        "watermark_position": site_config.get("watermark_position", "bottom-right"),
                        "watermark_opacity": _opacity(site_config.get("watermark_opacity")),
                    },
                )
                if proc_res.get("success") and proc_res.get("output_path"):
                    upload_path = Path(proc_res["output_path"])
                    logger.info(
                        f"✓ Tối ưu ảnh trước khi upload: {path.name} → {upload_path.name} "
                        f"({proc_res.get('original_size_kb')}KB → {proc_res.get('processed_size_kb')}KB, "
                        f"giảm {proc_res.get('saved_percent')}%)"
                    )
            except Exception as e:
                logger.warning(f"Không thể tối ưu ảnh {path.name}, tiếp tục với ảnh gốc: {e}")
                upload_path = path

        ext = upload_path.suffix.lower()
        if ext == ".webp":
            mime_type = "image/webp"
        elif ext in (".jpg", ".jpeg"):
            mime_type = "image/jpeg"
        elif ext == ".png":
            mime_type = "image/png"
        else:
            mime_type, _ = mimetypes.guess_type(str(upload_path))
            if not mime_type:
                mime_type = "image/jpeg"

        logger.info(f"Đang upload: {upload_path.name}")

        try:
            with open(upload_path, "rb") as f:
                headers = {
                    "Content-Disposition": f'attachment; filename="{ascii_filename(upload_path.name)}"',
                    "Content-Type": mime_type,
                }
                if requests.post is not _ORIG_POST:
                    response = requests.post(
                        endpoint,
                        auth=auth,
                        headers=headers,
                        data=f,
                        timeout=60,
                    )
                else:
                    response = session.post(
                        endpoint,
                        auth=auth,
                        headers=headers,
                        data=f,
                        timeout=60,
                    )

            if response.status_code in (200, 201):
                data = response.json()
                result = {
                    "id": data["id"],
                    "url": data["source_url"],
                    "filename": path.name,
                    "index": idx,   # vị trí trong danh sách gốc: ảnh lỗi không làm lệch [IMAGE_PLACEHOLDER_N]
                }
                results[idx] = result
                logger.info(f"✓ Upload thành công: {path.name} → {result['url']}")
            else:
                logger.error(
                    f"✗ Lỗi upload {path.name}: "
                    f"HTTP {response.status_code} - {response.text[:200]}"
                )
                with errors_lock:
                    errors.append(f"{path.name}: {describe_upload_error(response)}")

        except Exception as e:
            logger.error(f"✗ Lỗi upload {path.name}: {e}")
            with errors_lock:
                errors.append(f"{path.name}: {type(e).__name__}: {str(e)[:150]}")

    max_workers = min(4, len(image_paths))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_upload_single, idx, p) for idx, p in enumerate(image_paths)]
        for fut in futures:
            fut.result()

    return [r for r in results if r is not None]


def _opacity(value, default: float = 0.7) -> float:
    """Độ mờ watermark; 0 là giá trị hợp lệ (không được thay bằng mặc định)."""
    try:
        return default if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return default


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


def _ensure_updatable(site_config: dict, scope: str, wp_id: int | str) -> None:
    """
    Chặn cập nhật (PUT) một mục đã bị xoá hoặc đang nằm trong THÙNG RÁC.

    PUT status=publish lên mục trong thùng rác sẽ "sống lại" mà WordPress không chạy bước khôi phục, nên
    slug giữ nguyên dạng hỏng (vd. `__trashed-7`) và đường dẫn sản phẩm bị sai. Raise ValueError (có hướng dẫn).
    """
    item = get_item(site_config, scope, wp_id)
    label = "sản phẩm" if scope == "product" else "bài viết"
    if item is None:
        raise ValueError(
            f"{label.capitalize()} WordPress #{wp_id} không còn tồn tại (đã bị xoá). "
            f"Hãy dùng nút Đăng để tạo {label} mới."
        )
    if item.get("status") == "trash":
        raise ValueError(
            f"{label.capitalize()} WordPress #{wp_id} đang nằm trong THÙNG RÁC. Hãy khôi phục nó trong wp-admin "
            f"(Thùng rác → Khôi phục) rồi cập nhật lại, hoặc dùng nút Đăng để tạo {label} mới."
        )


@retry(stop=stop_after_attempt(2), wait=wait_fixed(3), reraise=True, retry=retry_if_exception(_should_retry_http))
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
    tag_ids: list[int] | None = None,
    existing_wp_id: int | str | None = None,
    scheduled_time: datetime | None = None,
) -> dict:
    """
    Đăng sản phẩm lên WooCommerce qua REST API (/wp-json/wc/v3/products).
    Sử dụng trực tiếp client_key và client_secret từ .env.
    Có `existing_wp_id` -> CẬP NHẬT sản phẩm đó (PUT /products/{id}) thay vì tạo mới.
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

    if status == "future" and scheduled_time:
        from core.timeutil import vn_to_utc_iso
        utc_iso = vn_to_utc_iso(scheduled_time)
        if utc_iso:
            payload["date_created_gmt"] = utc_iso

    clean_reg = _clean_price(regular_price)
    if clean_reg:
        payload["regular_price"] = clean_reg

    clean_sale = _clean_price(sale_price)
    if clean_sale:
        payload["sale_price"] = clean_sale

    if category_ids:
        payload["categories"] = [{"id": cid} for cid in category_ids]

    if tag_ids:
        payload["tags"] = [{"id": tid} for tid in tag_ids]

    if uploaded_images:
        images_payload = []
        for img in uploaded_images:
            if "id" in img and img["id"]:
                images_payload.append({"id": img["id"]})
            elif "url" in img and img["url"]:
                images_payload.append({"src": img["url"]})
        if images_payload:
            payload["images"] = images_payload

    if existing_wp_id:
        _ensure_updatable(site_config, "product", existing_wp_id)
        logger.info(f"Đang CẬP NHẬT sản phẩm WooCommerce #{existing_wp_id} tại {base_url} (status={status})...")
    else:
        logger.info(f"Đang tạo sản phẩm WooCommerce tại {base_url} (status={status})...")

    wc_params = _wc_params(site_config)
    s_get, s_post, s_put, _ = _req_callers()

    try:
        if existing_wp_id:
            response = _safe_call(s_put, f"{endpoint}/{existing_wp_id}", auth=auth, json=payload, params=wc_params, timeout=30)
        else:
            response = _safe_call(s_post, endpoint, auth=auth, json=payload, params=wc_params, timeout=30)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.error(f"Lỗi HTTP khi tạo sản phẩm: {e}\n{response.text[:500]}")
        if not existing_wp_id:
            _mark_create_unsafe_to_retry(e)
        raise
    except Exception as e:
        logger.error(f"Lỗi kết nối khi tạo sản phẩm: {e}")
        if not existing_wp_id:
            _mark_create_unsafe_to_retry(e)
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


@retry(stop=stop_after_attempt(2), wait=wait_fixed(3), reraise=True, retry=retry_if_exception(_should_retry_http))
def publish_post(
    title: str,
    html_content: str,
    uploaded_images: list[dict],
    site_config: dict,
    status: str = "draft",
    category_ids: list[int] | None = None,
    tag_ids: list[int] | None = None,
    existing_wp_id: int | str | None = None,
    scheduled_time: datetime | None = None,
) -> dict:
    """
    Đăng bài viết thông thường (Blog Post) lên WordPress qua REST API (/wp-json/wp/v2/posts).
    Cần WordPress Application Password (WP_USER + WP_APP_PASSWORD).
    Có `existing_wp_id` -> CẬP NHẬT bài đó (PUT /posts/{id}) thay vì tạo mới.
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

    if status == "future" and scheduled_time:
        from core.timeutil import vn_to_utc_iso
        utc_iso = vn_to_utc_iso(scheduled_time)
        if utc_iso:
            payload["date_gmt"] = utc_iso

    if category_ids:
        payload["categories"] = category_ids

    if tag_ids:
        payload["tags"] = tag_ids

    if uploaded_images and uploaded_images[0].get('id'):
        payload["featured_media"] = uploaded_images[0]["id"]

    if existing_wp_id:
        _ensure_updatable(site_config, "post", existing_wp_id)
        logger.info(f"Đang CẬP NHẬT bài blog #{existing_wp_id} tại {base_url} (status={status})...")
    else:
        logger.info(f"Đang đăng bài blog lên {base_url} (status={status})...")

    s_get, s_post, s_put, _ = _req_callers()

    try:
        if existing_wp_id:
            response = _safe_call(s_put, f"{endpoint}/{existing_wp_id}", auth=auth, json=payload, timeout=30)
        else:
            response = _safe_call(s_post, endpoint, auth=auth, json=payload, timeout=30)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.error(f"Lỗi HTTP khi đăng bài: {e}\n{response.text[:500]}")
        if not existing_wp_id:
            _mark_create_unsafe_to_retry(e)
        raise
    except Exception as e:
        logger.error(f"Lỗi kết nối khi đăng bài: {e}")
        if not existing_wp_id:
            _mark_create_unsafe_to_retry(e)
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

    by_index = {img["index"]: img for img in images if isinstance(img.get("index"), int)}
    last_index = max(by_index) if by_index else -1

    def replace_one(match: re.Match) -> str:
        # Lấy số N trong [IMAGE_PLACEHOLDER_N]
        n = int(match.group(1)) - 1  # convert sang 0-based
        if by_index and 0 <= n <= last_index:
            # Ảnh thứ N upload lỗi -> bỏ placeholder, không lấy ảnh khác thế chỗ
            return build_figure_html(by_index[n]) if n in by_index else ""
        if not by_index and 0 <= n < len(images):
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

    s_get, _, _, _ = _req_callers()

    # Thử endpoint categories (kiểm tra WP)
    try:
        r = _safe_call(s_get, f"{base_url}/wp-json/wp/v2/categories", timeout=10)
        if r.status_code == 200:
            logger.info(f"✓ Kết nối WP REST API thành công tới {base_url}")
            result['wp_ok'] = True
            # Thử lấy version nếu có auth
            wp_user = site_config.get("wp_user", "")
            if wp_user:
                r2 = _safe_call(s_get, f"{base_url}/wp-json/wp/v2/users/me", auth=auth, timeout=10)
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
    wc_params = _wc_params(site_config)
    try:
        r_wc = _safe_call(s_get, f"{base_url}/wp-json/wc/v3/", auth=wc_auth, params=wc_params, timeout=10)
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

    s_get, _, _, _ = _req_callers()
    try:
        response = _safe_call(s_get, endpoint, auth=auth, timeout=10)
        response.raise_for_status()
        cats = response.json()
        return [{"id": c["id"], "name": c["name"]} for c in cats]
    except Exception as e:
        logger.warning(f"Không lấy được danh sách category: {e}")
        return []


# ═════════════════════════════════════════════════════════════
# Taxonomy (category / tag)
# ═════════════════════════════════════════════════════════════

def _is_product_scope(scope: str) -> bool:
    return scope == "product"


def _taxonomy_url_and_auth(site_config: dict, kind: str, scope: str) -> tuple[str, HTTPBasicAuth]:
    """
    product -> WooCommerce API (wc/v3, dùng consumer key/secret)
    post    -> WordPress core API (wp/v2, dùng Application Password)
    kind: 'categories' | 'tags'
    """
    base = site_config["url"].rstrip("/")
    if _is_product_scope(scope):
        auth = HTTPBasicAuth(site_config["client_key"], site_config["client_secret"])
        return f"{base}/wp-json/wc/v3/products/{kind}", auth
    return f"{base}/wp-json/wp/v2/{kind}", _get_wp_auth(site_config)


def fetch_categories(site_config: dict, scope: str, per_page: int = 100, max_pages: int = 30) -> list[dict]:
    """
    Lấy TOÀN BỘ category của website (có phân trang). Khác get_categories(): hàm này RAISE khi lỗi
    để nơi gọi không lưu nhầm danh sách rỗng đè lên cache cũ.

    scope: 'product' (WooCommerce) | 'post' (blog). Trả về [{"id", "name", "parent"}].
    """
    url, auth = _taxonomy_url_and_auth(site_config, "categories", scope)
    result: list[dict] = []
    page = 1
    s_get, _, _, _ = _req_callers()
    while page <= max_pages:
        params: dict = {"per_page": per_page, "page": page, "hide_empty": "false"}
        if _is_product_scope(scope):
            params = _wc_params(site_config, params)
        response = _safe_call(
            s_get,
            url, auth=auth, timeout=15,
            params=params,
        )
        if response.status_code == 400 and page > 1:
            break  # WP trả 400 rest_post_invalid_page_number khi vượt trang cuối
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError(f"Phản hồi category không hợp lệ: {str(batch)[:200]}")
        result.extend(
            {"id": c["id"], "name": _html_unescape(c.get("name", "")), "parent": c.get("parent", 0) or 0}
            for c in batch
        )
        total_pages = response.headers.get("X-WP-TotalPages")
        if len(batch) < per_page or (total_pages and page >= int(total_pages)):
            break
        page += 1
    return result


def _html_unescape(text: str) -> str:
    """WP trả tên term đã escape (vd 'Quạt &amp; Máy')."""
    import html
    return html.unescape(text or "")


def _norm_name(name: str) -> str:
    import unicodedata
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", name or "")).strip().casefold()


def ensure_tags(site_config: dict, scope: str, names: list[str]) -> list[int]:
    """
    Với mỗi tên tag: tìm tag trùng tên (không phân biệt hoa/thường) trên site, chưa có thì tạo mới.
    Trả về danh sách id theo đúng thứ tự (đã khử trùng lặp). Tag lỗi riêng lẻ bị bỏ qua và ghi log,
    không làm hỏng cả bài đăng.
    """
    url, auth = _taxonomy_url_and_auth(site_config, "tags", scope)
    ids: list[int] = []
    seen_names: set[str] = set()
    s_get, s_post, _, _ = _req_callers()
    for raw in names:
        name = re.sub(r"\s+", " ", (raw or "")).strip()
        key = _norm_name(name)
        if not name or key in seen_names:
            continue
        seen_names.add(key)
        try:
            get_params: dict = {"search": name, "per_page": 100}
            post_params: dict = {}
            if _is_product_scope(scope):
                get_params = _wc_params(site_config, get_params)
                post_params = _wc_params(site_config, post_params)

            found = _safe_call(s_get, url, auth=auth, timeout=15, params=get_params)
            if found.status_code in (401, 403):
                logger.warning(f"Dừng kiểm tra tag do lỗi xác thực HTTP {found.status_code} tại {url}")
                break
            found.raise_for_status()
            match = next((t for t in found.json() if _norm_name(_html_unescape(t.get("name", ""))) == key), None)
            if match:
                tag_id = match["id"]
            else:
                created = _safe_call(s_post, url, auth=auth, json={"name": name}, params=post_params or None, timeout=15)
                if created.status_code in (401, 403):
                    logger.warning(f"Dừng kiểm tra tag do lỗi xác thực HTTP {created.status_code} tại {url}")
                    break
                if created.status_code == 400:
                    # Tag đã tồn tại (khác cách viết/slug): WP trả id trong data
                    data = (created.json() or {}).get("data", {}) or {}
                    tag_id = data.get("term_id") or data.get("resource_id")
                    if not tag_id:
                        created.raise_for_status()
                else:
                    created.raise_for_status()
                    tag_id = created.json()["id"]
            if tag_id not in ids:
                ids.append(int(tag_id))
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code in (401, 403):
                logger.warning(f"Dừng kiểm tra tag do lỗi xác thực HTTP {e.response.status_code} tại {url}: {e}")
                break
            logger.warning(f"Bỏ qua tag '{name}': {e}")
        except Exception as e:
            logger.warning(f"Bỏ qua tag '{name}': {e}")
    return ids


# ═════════════════════════════════════════════════════════════
# Đồng bộ: tìm / liệt kê / đọc (chỉ đọc) và đưa vào thùng rác
# ═════════════════════════════════════════════════════════════

def _items_url_and_auth(site_config: dict, scope: str) -> tuple[str, HTTPBasicAuth]:
    """product -> wc/v3/products (consumer key); post -> wp/v2/posts (Application Password)."""
    base = site_config["url"].rstrip("/")
    if _is_product_scope(scope):
        return f"{base}/wp-json/wc/v3/products", HTTPBasicAuth(site_config["client_key"], site_config["client_secret"])
    return f"{base}/wp-json/wp/v2/posts", _get_wp_auth(site_config)


def _normalize_item(raw: dict, scope: str) -> dict:
    """Đưa sản phẩm WC / bài WP về cùng một dạng: {id, title, status, url, modified, type}."""
    if _is_product_scope(scope):
        title = raw.get("name", "")
        url = raw.get("permalink", "")
        modified = raw.get("date_modified", "")
        modified_gmt = raw.get("date_modified_gmt", "")
    else:
        t = raw.get("title")
        title = t.get("rendered", "") if isinstance(t, dict) else (t or "")
        url = raw.get("link", "")
        modified = raw.get("modified", "")
        modified_gmt = raw.get("modified_gmt", "")
    return {
        "id": raw.get("id"),
        "title": _html_unescape(title),
        "status": raw.get("status", ""),
        "url": url,
        "modified": modified or "",              # giờ theo múi giờ của website (có thể là UTC)
        "modified_gmt": modified_gmt or "",      # luôn là UTC — dùng cái này để đổi sang GMT+7
        "type": "product" if _is_product_scope(scope) else "post",
    }


def list_items(
    site_config: dict, scope: str, page: int = 1, per_page: int = 20, status: str = "any", search: str = ""
) -> tuple[list[dict], int]:
    """
    CHỈ ĐỌC. Liệt kê sản phẩm/bài đang có trên website. Trả (items, tổng_số).
    RAISE khi lỗi mạng/HTTP để nơi gọi báo lỗi thay vì hiểu nhầm là website trống.
    """
    url, auth = _items_url_and_auth(site_config, scope)
    params: dict = {"per_page": per_page, "page": page, "status": status, "orderby": "date", "order": "desc"}
    if search:
        params["search"] = search
    if _is_product_scope(scope):
        params = _wc_params(site_config, params)
    s_get, _, _, _ = _req_callers()
    response = _safe_call(s_get, url, auth=auth, params=params, timeout=20)
    response.raise_for_status()
    batch = response.json()
    if not isinstance(batch, list):
        raise ValueError(f"Phản hồi danh sách không hợp lệ: {str(batch)[:200]}")
    total = int(response.headers.get("X-WP-Total") or len(batch))
    return [_normalize_item(b, scope) for b in batch], total


def get_item(site_config: dict, scope: str, wp_id: int | str) -> dict | None:
    """CHỈ ĐỌC. Lấy 1 sản phẩm/bài theo id; None nếu không còn (404). Lỗi khác thì raise."""
    url, auth = _items_url_and_auth(site_config, scope)
    params = _wc_params(site_config) if _is_product_scope(scope) else None
    s_get, _, _, _ = _req_callers()
    response = _safe_call(s_get, f"{url}/{wp_id}", auth=auth, params=params, timeout=20)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return _normalize_item(response.json(), scope)


def trash_item(site_config: dict, scope: str, wp_id: int | str) -> dict:
    """
    Đưa 1 sản phẩm/bài vào THÙNG RÁC của WordPress (khôi phục được trong wp-admin).
    Cố ý KHÔNG có tham số `force`: module này không bao giờ xóa vĩnh viễn.
    """
    url, auth = _items_url_and_auth(site_config, scope)
    params: dict = {"force": "false"}
    if _is_product_scope(scope):
        params = _wc_params(site_config, params)
    _, _, _, s_delete = _req_callers()
    response = _safe_call(s_delete, f"{url}/{wp_id}", auth=auth, params=params, timeout=30)
    response.raise_for_status()
    item = _normalize_item(response.json(), scope)
    item["status"] = item["status"] or "trash"
    return item


def update_item(site_config: dict, scope: str, wp_id: int | str, fields: dict) -> dict:
    """Cập nhật một số trường của bài viết/sản phẩm có sẵn trên WordPress (PUT, không tạo mới)."""
    url, auth = _items_url_and_auth(site_config, scope)
    params = _wc_params(site_config) if _is_product_scope(scope) else None
    _, _, s_put, _ = _req_callers()
    resp = _safe_call(s_put, f"{url}/{wp_id}", auth=auth, json=fields, params=params, timeout=20)
    resp.raise_for_status()
    return _normalize_item(resp.json(), scope)


def update_item_status(site_config: dict, scope: str, wp_id: int | str, new_status: str) -> dict:
    """Cập nhật trạng thái (status) của bài viết/sản phẩm trên WordPress (vd đổi từ future sang draft)."""
    return update_item(site_config, scope, wp_id, {"status": new_status})


def update_item_taxonomy(
    site_config: dict, scope: str, wp_id: int | str, category_ids: list[int], tag_ids: list[int]
) -> dict:
    """Ghi đè danh mục và tag của bài/sản phẩm có sẵn (WooCommerce cần dạng [{"id": ..}])."""
    if _is_product_scope(scope):
        fields = {"categories": [{"id": c} for c in category_ids], "tags": [{"id": t} for t in tag_ids]}
    else:
        fields = {"categories": list(category_ids), "tags": list(tag_ids)}
    return update_item(site_config, scope, wp_id, fields)
