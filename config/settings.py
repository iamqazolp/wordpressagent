"""
config/settings.py
Đọc cấu hình từ .env cho toàn bộ hệ thống WordPress Agent.
"""
from __future__ import annotations
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

# ── Cấu hình bài viết ────────────────────────────────────────
SEARCH_RESULT_COUNT = int(os.getenv("SEARCH_RESULT_COUNT", "5"))
POST_STATUS = os.getenv("POST_STATUS", "draft")

# ── Backward compatibility helpers ───────────────────────────
SITES: dict[str, dict] = {}


def load_sites() -> dict[str, dict]:
    """Tải danh sách website từ CSDL SQLite để tương thích ngược."""
    global SITES
    try:
        from db.database import SessionLocal
        from db import crud
        db = SessionLocal()
        try:
            configs = crud.get_all_site_configs(db)
            SITES.clear()
            SITES.update(configs)
            return SITES
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Chưa thể nạp cấu hình website từ DB: {e}")
        return SITES


def get_site_choices() -> list[str]:
    """Trả về danh sách tên website hiện có."""
    load_sites()
    return list(SITES.keys()) if SITES else ["(Chưa có website nào)"]
