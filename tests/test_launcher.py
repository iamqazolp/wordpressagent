"""Launcher: .env, cài đặt (stamp), bật/tắt app không cửa sổ, kill cây tiến trình, nút tắt app trong UI web."""
import shutil
import socket
import subprocess
import sys
import textwrap
import types

import pytest

from pathlib import Path

from launcher import core
from services import system as system_service
from ui import app_control


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── .env ─────────────────────────────────────────────────────────────────────

def test_read_and_update_env_preserve_other_lines(tmp_path):
    (tmp_path / ".env").write_text("# ghi chú\nGEMINI_API_KEY=\nENCRYPTION_KEY=abc==\nPORT='7861'\n", encoding="utf-8")
    assert core.read_env(tmp_path) == {"GEMINI_API_KEY": "", "ENCRYPTION_KEY": "abc==", "PORT": "7861"}
    core.update_env(tmp_path, {"GEMINI_API_KEY": "k123", "SERP_API_KEY": "s9"})
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "# ghi chú" in text and "ENCRYPTION_KEY=abc==" in text and "PORT='7861'" in text
    assert "GEMINI_API_KEY=k123" in text and text.rstrip().endswith("SERP_API_KEY=s9")
    assert core.read_env(tmp_path)["GEMINI_API_KEY"] == "k123"


def test_update_env_creates_file_and_ensure_env(tmp_path):
    core.update_env(tmp_path, {"A": "1"})
    assert core.read_env(tmp_path) == {"A": "1"}
    root = tmp_path / "proj"
    (root / "tools").mkdir(parents=True)
    (root / ".env.example").write_text("GEMINI_API_KEY=\nENCRYPTION_KEY=\n", encoding="utf-8")
    shutil.copy(Path(__file__).resolve().parent.parent / "tools" / "init_env.py", root / "tools" / "init_env.py")
    (root / "tools" / "__init__.py").write_text("", encoding="utf-8")
    sys.modules.pop("tools.init_env", None)
    sys.modules.pop("tools", None)
    try:
        assert core.ensure_env(root) == "CREATED"
        assert core.read_env(root)["ENCRYPTION_KEY"]
        assert core.ensure_env(root) == "EXISTS"
    finally:
        sys.path.remove(str(root))
        sys.modules.pop("tools.init_env", None)
        sys.modules.pop("tools", None)


# ── cài đặt ──────────────────────────────────────────────────────────────────

def test_venv_python_path_per_os(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "is_windows", lambda: True)
    assert core.venv_python(tmp_path).parts[-3:] == (".venv", "Scripts", "python.exe")
    monkeypatch.setattr(core, "is_windows", lambda: False)
    assert core.venv_python(tmp_path).parts[-3:] == (".venv", "bin", "python")


def test_no_window_flags_only_on_windows(monkeypatch):
    monkeypatch.setattr(core, "is_windows", lambda: False)
    assert core.no_window_flags() == 0
    monkeypatch.setattr(core, "is_windows", lambda: True)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    assert core.no_window_flags() == 0x08000000


def test_needs_install_follows_requirements_stamp(tmp_path):
    (tmp_path / "requirements.txt").write_text("gradio==1\n", encoding="utf-8")
    assert core.needs_install(tmp_path)                      # chưa có venv
    py = core.venv_python(tmp_path)
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    assert core.needs_install(tmp_path)                      # có venv nhưng chưa có stamp
    core._stamp_path(tmp_path).write_text(core.requirements_stamp(tmp_path), encoding="utf-8")
    assert not core.needs_install(tmp_path)
    (tmp_path / "requirements.txt").write_text("gradio==2\n", encoding="utf-8")
    assert core.needs_install(tmp_path)                      # cập nhật bản mới đổi requirements → cài lại


def test_python_ok():
    assert core.python_ok((3, 11, 0)) and core.python_ok((3, 12)) and not core.python_ok((3, 10, 9))


def test_install_rejects_old_python(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "python_ok", lambda *a: False)
    with pytest.raises(core.LauncherError, match="Python 3.11"):
        core.install(tmp_path, lambda s: None)


def test_run_logged_streams_lines_and_exit_code(tmp_path):
    lines = []
    code = core.run_logged([sys.executable, "-c", "print('a'); print('b')"], tmp_path, lines.append)
    assert code == 0 and lines == ["a", "b"]
    assert core.run_logged([sys.executable, "-c", "import sys; sys.exit(3)"], tmp_path, lines.append) == 3


# ── chạy / dừng app ──────────────────────────────────────────────────────────

FAKE_APP = textwrap.dedent("""
    import http.server, os, socketserver
    port = int(os.environ["FAKE_PORT"])
    print("fake app up", os.environ.get("APP_OPEN_BROWSER"), flush=True)
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        def log_message(self, *a): pass
    socketserver.TCPServer.allow_reuse_address = True
    socketserver.TCPServer(("127.0.0.1", port), H).serve_forever()
""")


@pytest.fixture
def fake_runner(tmp_path, monkeypatch):
    port = _free_port()
    (tmp_path / "app.py").write_text(FAKE_APP, encoding="utf-8")
    (tmp_path / ".env").write_text(f"PORT={port}\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_PORT", str(port))
    runner = core.AppRunner(tmp_path, python=sys.executable)
    yield runner, port, tmp_path
    runner.stop()


def test_runner_start_ready_stop_and_log(fake_runner):
    runner, port, root = fake_runner
    assert runner.port == port and runner.url == f"http://127.0.0.1:{port}"
    assert runner.state() == "stopped"
    runner.start()
    assert runner.wait_ready(timeout=20)
    assert runner.alive() and runner.state() == "running"
    runner.stop()
    assert not runner.alive() and runner.state() == "stopped"
    log = (root / "logs" / "app.log").read_text(encoding="utf-8")
    assert "fake app up false" in log                          # launcher tự mở trình duyệt → app không mở thêm


def test_runner_refuses_when_port_taken_by_others(fake_runner):
    runner, port, _ = fake_runner
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))
        s.listen()
        assert runner.state() == "external" and runner.external_running()
        with pytest.raises(core.PortBusy):
            runner.start()


def test_runner_missing_python_and_early_death(tmp_path):
    (tmp_path / ".env").write_text(f"PORT={_free_port()}\n", encoding="utf-8")
    with pytest.raises(core.LauncherError, match="venv"):
        core.AppRunner(tmp_path, python=str(tmp_path / "nope")).start()
    (tmp_path / "app.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    r = core.AppRunner(tmp_path, python=sys.executable)
    r.start()
    assert r.wait_ready(timeout=10) is False                   # tiến trình chết sớm → không chờ hết giờ
    r.stop()


def test_runner_bad_port_falls_back_to_default(tmp_path):
    (tmp_path / ".env").write_text("PORT=abc\n", encoding="utf-8")
    assert core.AppRunner(tmp_path, python=sys.executable).port == core.DEFAULT_PORT


def test_kill_process_tree_terminates_child():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    core.kill_process_tree(p)
    assert p.poll() is not None


# ── nút Tắt ứng dụng trong giao diện web ─────────────────────────────────────

def test_is_local_request():
    assert system_service.is_local_request("127.0.0.1", {})
    assert system_service.is_local_request("::1", {"User-Agent": "x"})
    assert not system_service.is_local_request("192.168.1.8", {})
    assert not system_service.is_local_request("127.0.0.1", {"X-Forwarded-For": "1.2.3.4"})   # qua đường hầm/proxy
    assert not system_service.is_local_request(None, None)


def test_schedule_shutdown_calls_exit_fn():
    import threading
    done = threading.Event()
    system_service.schedule_shutdown(0.01, exit_fn=done.set)
    assert done.wait(2)


def test_confirm_shutdown_only_for_local_requests(monkeypatch):
    calls = []
    monkeypatch.setattr(system_service, "schedule_shutdown", lambda *a, **k: calls.append(1))
    local = types.SimpleNamespace(client=types.SimpleNamespace(host="127.0.0.1"), headers={})
    remote = types.SimpleNamespace(client=types.SimpleNamespace(host="10.0.0.5"), headers={})
    tunneled = types.SimpleNamespace(client=types.SimpleNamespace(host="127.0.0.1"), headers={"x-forwarded-for": "8.8.8.8"})
    assert "Chỉ tắt được" in app_control.on_confirm_shutdown(remote)[2]
    assert "Chỉ tắt được" in app_control.on_confirm_shutdown(tunneled)[2]
    assert calls == []
    assert "đang tắt" in app_control.on_confirm_shutdown(local)[2]
    assert calls == [1]
    assert "Chỉ tắt được" in app_control.on_confirm_shutdown(None)[2] and calls == [1]


def test_wait_ready_reports_progress_and_app_log(tmp_path):
    from launcher import core

    r = core.AppRunner(tmp_path)
    r.log_path.parent.mkdir()
    r.log_path.write_text("loading gradio\n", encoding="utf-8")

    class P:
        def poll(self):
            return None

    r.proc = P()
    r.responding = lambda: False
    lines: list[str] = []
    assert r.wait_ready(timeout=6, poll=1, sleep=lambda _s: None, log=lines.append) is False
    assert any("loading gradio" in ln for ln in lines)
    assert any("Đang khởi động" in ln for ln in lines)


def test_read_env_handles_windows_bom_and_ansi(tmp_path):
    (tmp_path / ".env").write_bytes(b"\xef\xbb\xbfPORT=7999\nNOTE=caf\xe9\n")   # BOM của Notepad + 1 byte ANSI
    env = core.read_env(tmp_path)
    assert env["PORT"] == "7999" and "NOTE" in env
    core.update_env(tmp_path, {"PORT": "8001"})
    assert core.read_env(tmp_path)["PORT"] == "8001"
    assert (tmp_path / ".env").read_text(encoding="utf-8").count("PORT=") == 1


def test_runner_forces_env_port_and_refuses_after_shutdown(tmp_path, monkeypatch):
    port = _free_port()
    (tmp_path / ".env").write_text(f"PORT={port}\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("import os; print('port', os.environ['PORT'], flush=True)\n", encoding="utf-8")
    monkeypatch.setenv("PORT", "1")                            # PORT sót trong biến môi trường hệ thống
    r = core.AppRunner(tmp_path, python=sys.executable)
    r.start()
    r.proc.wait(timeout=20)
    r.stop()
    assert f"port {port}" in (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    r.shutdown()
    with pytest.raises(core.LauncherError):
        r.start()


def test_install_requirements_prefers_uv_and_falls_back_to_pip(tmp_path, monkeypatch):
    seen = []

    def fake_run(fail_uv):
        def run(cmd, cwd, log, env=None):
            seen.append((cmd[2:4], env))
            return 1 if (fail_uv and cmd[2] == "uv") else 0
        return run

    monkeypatch.setattr(core, "run_logged", fake_run(False))
    core.install_requirements("py", tmp_path, lambda s: None, {})
    assert [c for c, _ in seen] == [["pip", "install"], ["uv", "pip"]]
    assert seen[1][1]["UV_LINK_MODE"] == "copy"              # OneDrive / khác ổ đĩa: không dùng hardlink

    seen.clear()
    monkeypatch.setattr(core, "run_logged", fake_run(True))
    core.install_requirements("py", tmp_path, lambda s: None, {})
    assert [c for c, _ in seen][-1] == ["pip", "install"] and len(seen) == 4   # uv lỗi -> pip

    monkeypatch.setattr(core, "run_logged", lambda *a, **k: 1)
    with pytest.raises(core.LauncherError):
        core.install_requirements("py", tmp_path, lambda s: None, {})


@pytest.mark.skipif(sys.platform == "win32", reason="Windows dùng taskkill /T (đã có test riêng)")
def test_kill_process_tree_also_kills_grandchildren(tmp_path):
    import os
    import time

    pid_file = tmp_path / "grandchild.pid"
    code = (
        "import subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(p.pid))\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], **core.popen_group_kwargs())
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text():
            break
        time.sleep(0.05)
    grandchild = int(pid_file.read_text())
    core.kill_process_tree(proc)
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild, 0)                                  # cháu (vd. frpc) cũng đã bị tắt
