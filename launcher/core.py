"""
launcher/core.py — phần LOGIC của trình khởi động (không dùng giao diện, chỉ thư viện chuẩn của Python).

Trình khởi động chạy bằng Python hệ thống (trước khi có .venv), nên module này KHÔNG import gói nào ngoài stdlib.
Giao diện (launcher/gui.py) chỉ gọi các hàm ở đây, nhờ vậy kiểm thử được mà không cần màn hình.

Mọi tiến trình con trên Windows đều chạy với cờ CREATE_NO_WINDOW để KHÔNG hiện cửa sổ terminal.
"""
from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

MIN_PYTHON = (3, 11)
DEFAULT_PORT = 7860
LOG_MAX_BYTES = 2 * 1024 * 1024

Log = Callable[[str], None]


class LauncherError(Exception):
    """Lỗi có thông điệp thân thiện để hiện cho người dùng."""


class PortBusy(LauncherError):
    """Cổng của ứng dụng đang bị một tiến trình khác (không phải do launcher này mở) chiếm."""


# ── Đường dẫn & môi trường ────────────────────────────────────────────────────

def is_windows() -> bool:
    return os.name == "nt"


def no_window_flags() -> int:
    """Cờ để tiến trình con không bật cửa sổ console (chỉ có nghĩa trên Windows)."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if is_windows() else 0


def venv_python(root: Path) -> Path:
    sub = ("Scripts", "python.exe") if is_windows() else ("bin", "python")
    return Path(root) / ".venv" / sub[0] / sub[1]


def console_python() -> str:
    """Python hệ thống dùng để tạo venv. Dưới pythonw.exe thì chuyển sang python.exe cùng thư mục."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def read_version(root: Path) -> str:
    try:
        return (Path(root) / "VERSION").read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


def python_ok(version_info=None) -> bool:
    return tuple((version_info or sys.version_info)[:2]) >= MIN_PYTHON


# ── .env ──────────────────────────────────────────────────────────────────────

def read_env(root: Path) -> dict[str, str]:
    """Đọc .env thành dict (bỏ dòng trống/chú thích, bỏ cặp nháy bao ngoài)."""
    values: dict[str, str] = {}
    path = Path(root) / ".env"
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key.strip()] = val
    return values


def update_env(root: Path, updates: dict[str, str]) -> None:
    """Ghi/đổi các khoá trong .env, giữ nguyên mọi dòng khác (chú thích, thứ tự, ENCRYPTION_KEY...)."""
    path = Path(root) / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(updates)
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in pending:
            out.append(f"{key}={pending.pop(key)}")
        else:
            out.append(line)
    for key, val in pending.items():
        out.append(f"{key}={val}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def ensure_env(root: Path) -> str:
    """Tạo .env từ .env.example (kèm ENCRYPTION_KEY) nếu chưa có. Trả 'CREATED' hoặc 'EXISTS'."""
    root = Path(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from tools.init_env import ensure_env as _ensure

    return _ensure(root)


# ── Cài đặt ───────────────────────────────────────────────────────────────────

def requirements_stamp(root: Path) -> str:
    req = Path(root) / "requirements.txt"
    return hashlib.sha256(req.read_bytes()).hexdigest() if req.exists() else ""


def _stamp_path(root: Path) -> Path:
    return Path(root) / ".venv" / ".requirements.sha256"


def needs_install(root: Path) -> bool:
    """Chưa có môi trường ảo, hoặc requirements.txt đã đổi (vd. sau khi cập nhật bản mới)."""
    if not venv_python(root).exists():
        return True
    stamp = _stamp_path(root)
    return not stamp.exists() or stamp.read_text(encoding="utf-8").strip() != requirements_stamp(root)


def run_logged(cmd: list[str], cwd: Path, log: Log, env: dict | None = None) -> int:
    """Chạy lệnh (không cửa sổ), chuyển từng dòng đầu ra cho `log`. Trả mã thoát."""
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", creationflags=no_window_flags(),
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log(line)
    return proc.wait()


def install(root: Path, log: Log, python: str | None = None) -> None:
    """Tạo .venv, cài thư viện, tạo .env. Raise LauncherError khi thất bại."""
    root = Path(root)
    if not python_ok():
        raise LauncherError(
            f"Cần Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} trở lên (đang dùng {sys.version.split()[0]}). "
            "Tải tại https://www.python.org/downloads/ rồi mở lại."
        )
    env = {**os.environ, "PYTHONUTF8": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}

    ensure_env(root)  # tạo .env sớm: dù bước cài lỗi, file vẫn có sẵn

    if not venv_python(root).exists():
        log("Đang tạo môi trường riêng cho ứng dụng...")
        if run_logged([python or console_python(), "-m", "venv", str(root / ".venv")], root, log, env) != 0:
            raise LauncherError("Không tạo được môi trường ảo (.venv). Xem chi tiết trong khung nhật ký.")

    py = str(venv_python(root))
    log("Đang cài thư viện (vài phút ở lần đầu, cần Internet)...")
    run_logged([py, "-m", "pip", "install", "--upgrade", "pip", "-q"], root, log, env)
    if run_logged([py, "-m", "pip", "install", "-r", "requirements.txt"], root, log, env) != 0:
        raise LauncherError("Cài thư viện thất bại. Kiểm tra kết nối mạng rồi bấm thử lại.")
    log("Đang tối ưu để lần mở đầu tiên nhanh hơn (1–2 phút)...")
    run_logged([py, "-m", "compileall", "-q", "-j", "0", str(root / ".venv")], root, lambda _l: None, env)
    _stamp_path(root).write_text(requirements_stamp(root), encoding="utf-8")
    log("✓ Cài đặt xong.")


# ── Chạy / dừng ứng dụng ──────────────────────────────────────────────────────

def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def kill_process_tree(proc: subprocess.Popen, timeout: float = 8.0) -> None:
    """Tắt tiến trình và mọi tiến trình con (vd. đường hầm chia sẻ). Windows dùng taskkill, nơi khác dùng terminate."""
    if proc.poll() is not None:
        return
    if is_windows():
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=no_window_flags(), check=False,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout)


class AppRunner:
    """Quản lý tiến trình app.py: bật (không cửa sổ, ghi log ra file), kiểm tra sẵn sàng, tắt."""

    def __init__(self, root: Path, python: str | None = None, script: str = "app.py", log_name: str = "app.log"):
        self.root = Path(root)
        self.python = python or str(venv_python(self.root))
        self.script = script
        self.log_path = self.root / "logs" / log_name
        self.proc: subprocess.Popen | None = None
        self._log_file = None

    # cấu hình đọc từ .env mỗi lần để người dùng đổi PORT là ăn ngay
    @property
    def port(self) -> int:
        try:
            return int(read_env(self.root).get("PORT") or DEFAULT_PORT)
        except ValueError:
            return DEFAULT_PORT

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def responding(self) -> bool:
        """Có máy chủ web đang trả lời ở cổng của app không (mọi mã HTTP đều tính, vd. 401 khi bật đăng nhập)."""
        try:
            urllib.request.urlopen(self.url, timeout=1.5).close()
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            return False

    def external_running(self) -> bool:
        """Cổng đang bị chiếm nhưng không phải bởi tiến trình do launcher này mở."""
        return (not self.alive()) and port_in_use(self.port)

    def state(self) -> str:
        """'stopped' | 'starting' | 'running' | 'external'"""
        if self.alive():
            return "running" if self.responding() else "starting"
        return "external" if port_in_use(self.port) else "stopped"

    def _open_log(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if self.log_path.exists() and self.log_path.stat().st_size > LOG_MAX_BYTES:
            self.log_path.write_text("", encoding="utf-8")
        self._log_file = open(self.log_path, "ab")
        return self._log_file

    def start(self) -> None:
        if self.alive():
            return
        if port_in_use(self.port):
            raise PortBusy(
                f"Cổng {self.port} đang được dùng — có thể ứng dụng đã chạy ở nơi khác. "
                "Bấm «Mở trình duyệt» để vào luôn, hoặc đổi PORT trong .env."
            )
        if not Path(self.python).exists():
            raise LauncherError("Chưa cài đặt xong (thiếu môi trường .venv).")
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "APP_OPEN_BROWSER": "false",
               "GRADIO_ANALYTICS_ENABLED": "False", "HF_HUB_DISABLE_TELEMETRY": "1"}
        log = self._open_log()
        self._log_offset = log.tell()
        log.write(f"\n===== Khởi động {read_version(self.root)} =====\n".encode("utf-8"))
        log.flush()
        self.proc = subprocess.Popen(
            [self.python, self.script], cwd=str(self.root), env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, creationflags=no_window_flags(),
        )

    def wait_ready(
        self, timeout: float = 300.0, poll: float = 0.5, sleep: Callable[[float], None] | None = None,
        log: Log | None = None,
    ) -> bool:
        """Chờ app trả lời. False nếu hết giờ hoặc tiến trình chết sớm. `log` nhận tiến độ + dòng mới của app.log."""
        import time

        sleep = sleep or time.sleep
        waited = 0.0
        next_note = 5.0
        while waited < timeout:
            if not self.alive():
                return False
            if self.responding():
                return True
            sleep(poll)
            waited += poll
            if log and waited >= next_note:
                next_note += 5.0
                for line in self._new_log_lines():
                    log("  app: " + line)
                log(f"Đang khởi động… {int(waited)}s (lần đầu có thể mất 1–3 phút, đừng tắt)")
        return False

    def _new_log_lines(self) -> list[str]:
        try:
            with open(self.log_path, "rb") as f:
                f.seek(getattr(self, "_log_offset", 0))
                data = f.read()
                self._log_offset = f.tell()
        except OSError:
            return []
        return [ln for ln in data.decode("utf-8", "replace").splitlines() if ln.strip()][-5:]

    def stop(self) -> None:
        if self.proc is not None:
            kill_process_tree(self.proc)
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None


def run_backup(root: Path, log: Log | None = None) -> str:
    """Chạy tools/backup.py bằng Python của app (không cửa sổ). Trả dòng kết quả cuối cùng."""
    lines: list[str] = []
    env = {**os.environ, "PYTHONUTF8": "1"}
    code = run_logged([str(venv_python(root)), "tools/backup.py"], Path(root), lambda s: (lines.append(s), log and log(s)), env)
    if code != 0:
        raise LauncherError("Sao lưu thất bại: " + (lines[-1] if lines else "không rõ lỗi"))
    return lines[-1] if lines else "Đã sao lưu."
