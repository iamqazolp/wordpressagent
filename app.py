"""
app.py
Entry point cho WordPress Agent.
Chạy lệnh: python app.py
Sau đó mở trình duyệt: http://localhost:7860
"""
from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

# Tải biến môi trường trước khi import gì khác
load_dotenv()

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    """Khởi động ứng dụng WordPress Agent."""
    print("\n" + "=" * 55)
    print("  🌟 WordPress Agent — Đa Website & Tự Động Hóa")
    print("=" * 55)

    # Khởi tạo database (tạo bảng + migrate sites.json nếu có)
    from db.database import init_db, SessionLocal
    from db import crud

    init_db()

    # Hiển thị thông tin websites
    db = SessionLocal()
    try:
        sites = crud.get_all_sites(db)
        print(f"\n✓  Database: OK")
        print(f"✓  Số lượng website đang quản lý: {len(sites)}")
        for site in sites:
            print(f"   - {site.name}: {site.url}")

        templates = crud.get_all_templates(db)
        print(f"✓  Số lượng prompt template: {len(templates)}")
    finally:
        db.close()

    # Kiểm tra API key
    from config import settings
    if settings.GEMINI_API_KEY:
        key_preview = settings.GEMINI_API_KEY[:8] + "..."
        print(f"✓  Gemini API Key: {key_preview}")
    else:
        print("⚠  Chưa cấu hình GEMINI_API_KEY trong .env")

    if settings.SERP_API_KEY:
        print(f"✓  SerpAPI Key: Đã cấu hình")
    else:
        print("ℹ  SerpAPI Key: Chưa có (sẽ dùng URL tham khảo thủ công)")

    # Khởi động Post Scheduler (APScheduler)
    from core.scheduler import init_scheduler
    init_scheduler()

    # Tạo và khởi chạy Gradio UI
    from ui.main_ui import create_app
    import gradio as gr
    import os

    demo = create_app()

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "7860"))

    print(f"\n👉 Mở trình duyệt tại: http://{host}:{port}\n")

    demo.launch(
        server_name=host,
        server_port=port,
        share=False,
        inbrowser=True,
        theme=gr.themes.Soft(primary_hue="blue"),
    )


if __name__ == "__main__":
    main()
