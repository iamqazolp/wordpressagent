"""
launcher/gui.py — cửa sổ nhỏ để cài đặt, chạy, mở và DỪNG WordPress Agent mà không cần dùng terminal.

Chỉ chứa phần giao diện (tkinter có sẵn trong Python); mọi logic nằm ở launcher/core.py.
Việc nặng (cài đặt, bật/tắt app, sao lưu) chạy ở luồng nền, kết quả chuyển về luồng giao diện qua hàng đợi.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from launcher import core

GEMINI_KEYS_URL = "https://aistudio.google.com/app/apikey"
LOG_LINES = 400

STATE_TEXT = {
    "stopped": ("⚪", "Ứng dụng đang tắt"),
    "starting": ("🟡", "Đang khởi động..."),
    "running": ("🟢", "Đang chạy"),
    "external": ("🟠", "Đã có ứng dụng chạy ở cổng này (không do cửa sổ này mở)"),
}


def open_path(path: Path) -> None:
    """Mở file/thư mục bằng chương trình mặc định của hệ điều hành."""
    if core.is_windows():
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class LauncherApp:
    def __init__(self, win: tk.Tk, root: Path, auto_start: bool = True):
        self.win = win
        self.root = Path(root)
        self.runner = core.AppRunner(self.root)
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.state = "stopped"
        self._opened_browser = False
        self._closing = False

        win.title(f"WordPress Agent v{core.read_version(self.root)}")
        win.geometry("560x430")
        win.minsize(520, 380)
        win.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build()

        threading.Thread(target=self._poll_loop, daemon=True).start()
        win.after(100, self._pump)
        if auto_start:
            win.after(300, lambda: self.start_flow(open_browser=True))

    # ── giao diện ────────────────────────────────────────────────────────────
    def _build(self) -> None:
        pad = {"padx": 12, "pady": 6}
        self.status_var = tk.StringVar(value="⚪ Ứng dụng đang tắt")
        ttk.Label(self.win, textvariable=self.status_var, font=("Segoe UI", 13, "bold")).pack(anchor="w", **pad)
        self.progress = ttk.Progressbar(self.win, mode="indeterminate")
        self.progress.pack(fill="x", padx=12)

        row1 = ttk.Frame(self.win)
        row1.pack(fill="x", **pad)
        self.btn_start = ttk.Button(row1, text="▶ Khởi động", command=lambda: self.start_flow(open_browser=True))
        self.btn_open = ttk.Button(row1, text="🌐 Mở trình duyệt", command=self.open_browser)
        self.btn_stop = ttk.Button(row1, text="⏹ Dừng ứng dụng", command=self.stop_app)
        self.btn_restart = ttk.Button(row1, text="🔄 Khởi động lại", command=self.restart_app)
        for b in (self.btn_start, self.btn_open, self.btn_stop, self.btn_restart):
            b.pack(side="left", padx=(0, 6))

        row2 = ttk.Frame(self.win)
        row2.pack(fill="x", padx=12, pady=(0, 6))
        self.btn_keys = ttk.Button(row2, text="🔑 Khoá API…", command=self.open_settings)
        self.btn_backup = ttk.Button(row2, text="💾 Sao lưu", command=self.backup)
        self.btn_log = ttk.Button(row2, text="📄 Nhật ký", command=self.open_log)
        for b in (self.btn_keys, self.btn_backup, self.btn_log):
            b.pack(side="left", padx=(0, 6))

        ttk.Label(self.win, text="Chi tiết:").pack(anchor="w", padx=12)
        frame = ttk.Frame(self.win)
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.log_box = tk.Text(frame, height=10, wrap="word", state="disabled", font=("Consolas", 9))
        scroll = ttk.Scrollbar(frame, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=scroll.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        busy = self.busy
        can_stop = self.runner.alive() and not busy
        states = {
            self.btn_start: self.state in ("stopped",) and not busy,
            self.btn_open: self.state in ("running", "external") and not busy,
            self.btn_stop: can_stop,
            self.btn_restart: can_stop,
            self.btn_keys: not busy,
            self.btn_backup: not busy and core.venv_python(self.root).exists(),
            self.btn_log: True,
        }
        for btn, on in states.items():
            btn.state(["!disabled"] if on else ["disabled"])

    def set_status(self, state: str, extra: str = "") -> None:
        self.state = state
        icon, text = STATE_TEXT.get(state, ("", state))
        if state == "running":
            text += f" — {self.runner.url}"
        if state == "external":
            text = f"Đã có ứng dụng chạy ở cổng {self.runner.port} (không do cửa sổ này mở)"
        self.status_var.set(f"{icon} {extra or text}")
        self._refresh_buttons()

    def log(self, line: str) -> None:
        self.events.put(("log", line))

    def _append_log(self, line: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line + "\n")
        if int(self.log_box.index("end-1c").split(".")[0]) > LOG_LINES:
            self.log_box.delete("1.0", "50.0")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ── luồng nền ↔ giao diện ────────────────────────────────────────────────
    def run_bg(self, work: Callable[[], object], done: Callable[[object, Exception | None], None], status: str | None = None) -> None:
        self.busy = True
        if status:
            self.status_var.set(f"🟡 {status}")
        self.progress.start(12)
        self._refresh_buttons()

        def target():
            try:
                result, err = work(), None
            except Exception as e:  # mọi lỗi đều quay về giao diện để báo
                result, err = None, e
            self.events.put(("done", done, result, err))

        threading.Thread(target=target, daemon=True).start()

    def _pump(self) -> None:
        try:
            while True:
                ev = self.events.get_nowait()
                if ev[0] == "log":
                    self._append_log(ev[1])
                elif ev[0] == "state":
                    if not self.busy:
                        self.set_status(ev[1])
                elif ev[0] == "done":
                    self.busy = False
                    self.progress.stop()
                    ev[1](ev[2], ev[3])
                    self._refresh_buttons()
        except queue.Empty:
            pass
        if not self._closing:
            self.win.after(100, self._pump)

    def _poll_loop(self) -> None:
        import time

        while not self._closing:
            try:
                self.events.put(("state", self.runner.state()))
            except Exception:
                pass
            time.sleep(1.5)

    # ── hành động ────────────────────────────────────────────────────────────
    def start_flow(self, open_browser: bool = True) -> None:
        """Cài đặt (nếu cần) → hỏi khoá API (nếu thiếu) → bật ứng dụng → mở trình duyệt."""
        if self.busy:
            return
        if self.runner.alive() or self.state in ("running", "external"):
            if open_browser:
                self.open_browser()
            return

        def work():
            if core.needs_install(self.root):
                core.install(self.root, self.log)
            else:
                core.ensure_env(self.root)
            return True

        def done(_res, err):
            if err:
                return self._fail("Cài đặt chưa xong", err)
            if not core.read_env(self.root).get("GEMINI_API_KEY") and not getattr(self, "_asked_key", False):
                self._asked_key = True
                messagebox.showinfo("Cần khoá Gemini", "Điền khoá Gemini API (bắt buộc để AI viết bài).")
                self.open_settings(then=lambda: self._launch(open_browser))
                return
            self._launch(open_browser)

        status = "Đang cài đặt lần đầu (vài phút, cần Internet)..." if core.needs_install(self.root) else "Đang chuẩn bị..."
        self.run_bg(work, done, status)

    def _launch(self, open_browser: bool) -> None:
        def work():
            self.runner.start()
            return self.runner.wait_ready(log=self.log)

        def done(ready, err):
            if isinstance(err, core.PortBusy):
                self.set_status("external")
                messagebox.showinfo("Ứng dụng đã chạy", str(err))
                return
            if err:
                return self._fail("Không khởi động được ứng dụng", err)
            if not ready:
                return self._fail(
                    "Ứng dụng không phản hồi",
                    core.LauncherError(f"Bấm «Nhật ký» để xem lỗi. Tệp: {self.runner.log_path}"),
                )
            self.set_status("running")
            if open_browser and not self._opened_browser:
                self._opened_browser = True
                self.open_browser()

        self.run_bg(work, done, "Đang khởi động ứng dụng (lần đầu 1–3 phút)...")

    def _fail(self, title: str, err: Exception) -> None:
        self.log(f"✗ {err}")
        self.set_status(self.runner.state())
        messagebox.showerror(title, str(err))

    def open_browser(self) -> None:
        webbrowser.open(self.runner.url)

    def stop_app(self) -> None:
        if self.busy or not self.runner.alive():
            return
        self.run_bg(lambda: self.runner.stop(), lambda _r, _e: self.set_status("stopped"), "Đang dừng ứng dụng...")

    def restart_app(self) -> None:
        if self.busy:
            return
        self._opened_browser = True  # khởi động lại không mở thêm tab mới

        def work():
            self.runner.stop()
            self.runner.start()
            return self.runner.wait_ready(log=self.log)

        def done(ready, err):
            if err:
                return self._fail("Không khởi động lại được", err)
            self.set_status("running" if ready else self.runner.state())

        self.run_bg(work, done, "Đang khởi động lại...")

    def backup(self) -> None:
        def done(res, err):
            if err:
                return self._fail("Sao lưu thất bại", err)
            messagebox.showinfo("Đã sao lưu", str(res))

        self.run_bg(lambda: core.run_backup(self.root, self.log), done, "Đang sao lưu...")

    def open_log(self) -> None:
        path = self.runner.log_path
        if not path.exists():
            messagebox.showinfo("Nhật ký", "Chưa có nhật ký (ứng dụng chưa chạy lần nào).")
            return
        open_path(path)

    def open_settings(self, then: Callable[[], None] | None = None) -> None:
        """Hộp thoại nhập khoá API, ghi thẳng vào .env (giữ nguyên các dòng khác)."""
        core.ensure_env(self.root)
        env = core.read_env(self.root)
        dlg = tk.Toplevel(self.win)
        dlg.title("Khoá API")
        dlg.transient(self.win)
        dlg.resizable(False, False)
        entries: dict[str, ttk.Entry] = {}
        fields = (
            ("GEMINI_API_KEY", "Khoá Gemini API (bắt buộc)"),
            ("SERP_API_KEY", "Khoá SerpAPI (tuỳ chọn, để tìm tài liệu tham khảo)"),
        )
        show_var = tk.BooleanVar(value=False)
        for i, (key, label) in enumerate(fields):
            ttk.Label(dlg, text=label).grid(row=i * 2, column=0, sticky="w", padx=12, pady=(10, 0))
            e = ttk.Entry(dlg, width=58, show="*")
            e.insert(0, env.get(key, ""))
            e.grid(row=i * 2 + 1, column=0, padx=12, pady=2)
            entries[key] = e

        def toggle():
            for e in entries.values():
                e.configure(show="" if show_var.get() else "*")

        ttk.Checkbutton(dlg, text="Hiện khoá", variable=show_var, command=toggle).grid(row=4, column=0, sticky="w", padx=12, pady=4)
        link = ttk.Label(dlg, text="Lấy khoá Gemini ở đâu?", foreground="#1381f0", cursor="hand2")
        link.grid(row=5, column=0, sticky="w", padx=12)
        link.bind("<Button-1>", lambda _e: webbrowser.open(GEMINI_KEYS_URL))

        def save():
            core.update_env(self.root, {k: e.get().strip() for k, e in entries.items()})
            dlg.destroy()
            self.log("✓ Đã lưu khoá API vào .env")
            if then:
                then()
            elif self.runner.alive() and messagebox.askyesno("Khởi động lại?", "Cần khởi động lại để áp dụng khoá mới. Khởi động lại ngay?"):
                self.restart_app()

        def skip():
            dlg.destroy()
            if then:
                then()

        btns = ttk.Frame(dlg)
        btns.grid(row=6, column=0, sticky="e", padx=12, pady=10)
        ttk.Button(btns, text="Lưu", command=save).pack(side="right")
        ttk.Button(btns, text="Bỏ qua" if then else "Đóng", command=skip).pack(side="right", padx=6)
        dlg.protocol("WM_DELETE_WINDOW", skip)
        dlg.grab_set()

    def on_close(self) -> None:
        if self.runner.alive():
            if not messagebox.askyesno("Thoát", "Ứng dụng đang chạy. Tắt ứng dụng và thoát?"):
                return
            self.runner.stop()
        self._closing = True
        self.win.destroy()


def main(root: Path) -> None:
    root = Path(root)
    win = tk.Tk()
    if not core.python_ok():
        messagebox.showerror(
            "Cần Python mới hơn",
            f"Cần Python {core.MIN_PYTHON[0]}.{core.MIN_PYTHON[1]} trở lên (đang dùng {sys.version.split()[0]}).\n"
            "Tải tại https://www.python.org/downloads/ (nhớ tick «Add python.exe to PATH»).",
        )
        return
    LauncherApp(win, root)
    win.mainloop()
