"""
config/settings.py
Đọc cấu hình từ .env và cung cấp cho toàn bộ ứng dụng.
Thiết kế hỗ trợ nhiều website - chỉ cần thêm vào .env về sau.

Xác thực WordPress có 2 loại:
  - WooCommerce API keys (client_key/client_secret): chỉ dùng cho WooCommerce API
  - WordPress Application Password (wp_user/wp_app_password): dùng để đăng bài
    Tạo tại: WP Admin → Users → Profile → Application Passwords
"""
from __future__ import annotations
from dotenv import load_dotenv
import os

load_dotenv()

# ── Google Gemini ────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://api.shopaikey.com")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ── SerpAPI (tìm kiếm Google) ────────────────────────────────
SERP_API_KEY = os.getenv("SERP_API_KEY", "")

# ── Danh sách các website WooCommerce đang quản lý ──────────
SITES: dict[str, dict] = {}


def _load_site(name: str, url_key: str, ck_key: str, cs_key: str,
               wp_user_key: str = "", wp_pass_key: str = ""):
    url = os.getenv(url_key, "").strip().rstrip("/")
    ck  = os.getenv(ck_key, "").strip()
    cs  = os.getenv(cs_key, "").strip()
    if url and ck and cs:
        if not url.startswith("http"):
            url = "https://" + url
        SITES[name] = {
            "url": url,
            "client_key": ck,
            "client_secret": cs,
            # WordPress Application Password (để đăng bài)
            "wp_user":         os.getenv(wp_user_key, "").strip() if wp_user_key else "",
            "wp_app_password": os.getenv(wp_pass_key, "").strip() if wp_pass_key else "",
        }


# Site mặc định (đã có trong .env)
_load_site(
    name=os.getenv("url", "khodentrangtri.com"),
    url_key="url",
    ck_key="client_key",
    cs_key="client_secret",
    wp_user_key="WP_USER",
    wp_pass_key="WP_APP_PASSWORD",
)

# Hỗ trợ thêm site mới:
# thêm SITE2_URL, SITE2_CLIENT_KEY, SITE2_CLIENT_SECRET vào .env
for i in range(2, 10):
    prefix = f"SITE{i}_"
    _load_site(
        name=os.getenv(f"{prefix}NAME", f"site{i}"),
        url_key=f"{prefix}URL",
        ck_key=f"{prefix}CLIENT_KEY",
        cs_key=f"{prefix}CLIENT_SECRET",
    )

DEFAULT_SITE = list(SITES.keys())[0] if SITES else None

# ── Cấu hình viết bài ────────────────────────────────────────
SEARCH_RESULT_COUNT = 5          # Số bài tự tìm trên Google
POST_STATUS = "draft"            # "draft" = nháp, "publish" = đăng thẳng
CTA_PHONE = os.getenv("CTA_PHONE", "")
CTA_ADDRESS = os.getenv("CTA_ADDRESS", "")
