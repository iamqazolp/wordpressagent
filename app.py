"""
app.py
Entry point cho WordPress Agent.
Chạy lệnh: python app.py
Sau đó mở trình duyệt: http://localhost:7860
"""
from __future__ import annotations

import logging
import os
import sys

# Tắt telemetry của Gradio và Hugging Face để tránh delay mạng lúc khởi động
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

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
    try:
        from pathlib import Path
        version = (Path(__file__).parent / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = "dev"
    print(f"  🌟 WordPress Agent v{version} — Đa Website & Tự Động Hóa")
    print("=" * 55)

    # Khởi tạo database (tạo bảng + migrate sites.json nếu có)
    from db.database import init_db, SessionLocal
    from db import crud

    init_db()

    # Sao lưu DB tự động (tối đa 1 lần/20 giờ, giữ 7 bản). Không bao giờ làm hỏng việc khởi động.
    from core.backup import auto_backup
    auto_backup()

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

    # Bảo mật: share công khai và đăng nhập đều cấu hình qua .env, không hardcode.
    share = os.getenv("APP_SHARE", "false").strip().lower() in ("1", "true", "yes", "on")
    app_user = os.getenv("APP_USER", "").strip()
    app_password = os.getenv("APP_PASSWORD", "").strip()
    auth = (app_user, app_password) if app_user and app_password else None

    if share and auth is None:
        print("✗  APP_SHARE=true nhưng chưa đặt APP_USER/APP_PASSWORD trong .env.")
        print("   Từ chối mở link công khai khi không có mật khẩu. Hãy đặt cả hai biến rồi chạy lại.")
        sys.exit(1)
    if auth is None and host not in ("127.0.0.1", "localhost"):
        print(f"⚠  HOST={host} nhưng chưa đặt APP_USER/APP_PASSWORD — ai trong mạng cũng truy cập được.")
    print(f"✓  Đăng nhập: {'bật' if auth else 'tắt'} | Link công khai: {'bật' if share else 'tắt'}")

    print(f"\n👉 Mở trình duyệt tại: http://{host}:{port}\n")

    demo.launch(
        server_name=host,
        server_port=port,
        share=share,
        auth=auth,
        inbrowser=os.getenv("APP_OPEN_BROWSER", "true").strip().lower() in ("1", "true", "yes", "on"),
        theme=gr.themes.Soft(primary_hue="blue"),
    )


if __name__ == "__main__":
    main()
