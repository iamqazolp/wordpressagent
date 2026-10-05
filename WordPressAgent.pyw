"""
WordPress Agent — bấm đúp file này để cài đặt/chạy/dừng ứng dụng (không cần mở terminal).
Đuôi .pyw: Python chạy mà không bật cửa sổ đen.
"""
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

try:
    from launcher.gui import main

    main(ROOT)
except Exception:  # không có console nên phải tự ghi lỗi và hiện hộp thoại
    detail = traceback.format_exc()
    try:
        (ROOT / "logs").mkdir(exist_ok=True)
        (ROOT / "logs" / "launcher.log").write_text(detail, encoding="utf-8")
    except OSError:
        pass
    try:
        import tkinter
        from tkinter import messagebox

        tkinter.Tk().withdraw()
        messagebox.showerror("WordPress Agent", "Không mở được trình khởi động.\n\n" + detail[-900:])
    except Exception:
        pass
