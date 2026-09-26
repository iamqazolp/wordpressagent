"""
config/settings.py
Đọc cấu hình từ .env và quản lý danh sách website trong config/sites.json.
Hỗ trợ thêm / sửa / xóa website trực tiếp từ giao diện.
"""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

# ── Google Gemini ────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://api.shopaikey.com")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

# ── SerpAPI (tìm kiếm Google) ────────────────────────────────
SERP_API_KEY = os.getenv("SERP_API_KEY", "")

# ── Cấu hình viết bài ────────────────────────────────────────
SEARCH_RESULT_COUNT = 5          # Số bài tự tìm trên Google
POST_STATUS = "draft"            # "draft" = nháp, "publish" = đăng thẳng

# ── Đường dẫn lưu file sites.json ─────────────────────────────
SITES_FILE = Path(__file__).parent / "sites.json"

# Danh sách các website WooCommerce đang quản lý (in-memory)
SITES: dict[str, dict] = {}


def _clean_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if url and not url.startswith("http"):
        url = "https://" + url
    return url


def _seed_from_env() -> dict[str, dict]:
    """Khởi tạo danh sách sites ban đầu từ file .env nếu sites.json chưa tồn tại."""
    initial_sites = {}

    # Site mặc định từ .env
    default_url = os.getenv("url", "").strip()
    default_ck = os.getenv("client_key", "").strip()
    default_cs = os.getenv("client_secret", "").strip()
    if default_url and default_ck and default_cs:
        site_name = default_url.replace("https://", "").replace("http://", "").rstrip("/")
        initial_sites[site_name] = {
            "name": site_name,
            "url": _clean_url(default_url),
            "client_key": default_ck,
            "client_secret": default_cs,
            "wp_user": os.getenv("WP_USER", "").strip(),
            "wp_app_password": os.getenv("WP_APP_PASSWORD", "").strip(),
        }

    # Các site SITE2...SITE9 từ .env (nếu có)
    for i in range(2, 10):
        prefix = f"SITE{i}_"
        s_url = os.getenv(f"{prefix}URL", "").strip()
        s_ck = os.getenv(f"{prefix}CLIENT_KEY", "").strip()
        s_cs = os.getenv(f"{prefix}CLIENT_SECRET", "").strip()
        s_name = os.getenv(f"{prefix}NAME", "").strip() or f"Site {i}"
        if s_url and s_ck and s_cs:
            initial_sites[s_name] = {
                "name": s_name,
                "url": _clean_url(s_url),
                "client_key": s_ck,
                "client_secret": s_cs,
                "wp_user": os.getenv(f"{prefix}WP_USER", "").strip(),
                "wp_app_password": os.getenv(f"{prefix}WP_APP_PASSWORD", "").strip(),
            }

    return initial_sites


def load_sites() -> dict[str, dict]:
    """Tải danh sách website từ sites.json (hoặc khởi tạo từ .env nếu chưa có)."""
    global SITES
    if SITES_FILE.exists():
        try:
            with open(SITES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    SITES.clear()
                    SITES.update(data)
                    return SITES
        except Exception as e:
            logger.error(f"Lỗi khi đọc file sites.json: {e}")

    # Nếu chưa có sites.json, seed từ .env và lưu lại
    initial = _seed_from_env()
    SITES.clear()
    SITES.update(initial)
    _save_to_file(SITES)
    return SITES


def _save_to_file(sites_data: dict[str, dict]) -> bool:
    """Ghi đè danh sách sites vào sites.json."""
    try:
        with open(SITES_FILE, "w", encoding="utf-8") as f:
            json.dump(sites_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Lỗi khi ghi file sites.json: {e}")
        return False


def save_site(
    name: str,
    url: str,
    client_key: str,
    client_secret: str,
    wp_user: str = "",
    wp_app_password: str = "",
    old_name: str = "",
) -> tuple[bool, str]:
    """
    Thêm mới hoặc chỉnh sửa 1 website.
    Nếu old_name được truyền vào và khác name, đổi tên website.
    """
    name = name.strip()
    url = _clean_url(url)
    client_key = client_key.strip()
    client_secret = client_secret.strip()
    wp_user = wp_user.strip()
    wp_app_password = wp_app_password.strip()

    if not name:
        return False, "❌ Tên website không được để trống!"
    if not url:
        return False, "❌ URL website không được để trống!"
    if not client_key or not client_secret:
        return False, "❌ Cần nhập đầy đủ WooCommerce Client Key và Client Secret!"

    # Nếu đổi tên từ một site cũ
    if old_name and old_name in SITES and old_name != name:
        del SITES[old_name]

    SITES[name] = {
        "name": name,
        "url": url,
        "client_key": client_key,
        "client_secret": client_secret,
        "wp_user": wp_user,
        "wp_app_password": wp_app_password,
    }

    if _save_to_file(SITES):
        return True, f"✅ Đã lưu cấu hình cho website: {name}"
    else:
        return False, "❌ Lỗi khi ghi file dữ liệu sites.json!"


def delete_site(name: str) -> tuple[bool, str]:
    """Xóa 1 website khỏi danh sách."""
    name = name.strip()
    if name not in SITES:
        return False, f"❌ Không tìm thấy website '{name}' để xóa!"

    if len(SITES) <= 1:
        return False, "❌ Không thể xóa vì hệ thống cần giữ lại ít nhất 1 website!"

    del SITES[name]
    if _save_to_file(SITES):
        return True, f"✅ Đã xóa thành công website: {name}"
    else:
        return False, "❌ Lỗi khi cập nhật file dữ liệu!"


def get_site_choices() -> list[str]:
    """Trả về danh sách tên các website có sẵn."""
    if not SITES:
        load_sites()
    return list(SITES.keys()) if SITES else ["(Chưa có website nào)"]


# Tải dữ liệu ban đầu
load_sites()
DEFAULT_SITE = list(SITES.keys())[0] if SITES else None
