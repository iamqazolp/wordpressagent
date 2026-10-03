"""
Bảo vệ kiến trúc phân lớp bằng cách quét import (AST) — không import module nên chạy nhanh, không cần gradio.

  ui/  ──►  services/  ──►  core/  ──►  db/
  * services/, core/, db/ không import gradio (để đổi UI/ thêm API mà không đụng nghiệp vụ).
  * ui/ không import db/ (mọi truy cập dữ liệu đi qua services/).
  * Không import ngược chiều: services/ và core/ không import ui/; core/ và db/ không import services/;
    db/ chỉ được dùng core.timeutil (helper thuần).
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI_FRAMEWORKS = {"gradio", "streamlit", "nicegui", "flet"}


def _imports(path: Path) -> set[str]:
    """Tên module gốc đầy đủ của mọi import trong file (vd 'db.crud', 'gradio')."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module)
            if node.module in {"db", "services", "ui", "core"}:  # `from db import crud` -> db.crud
                mods.update(f"{node.module}.{a.name}" for a in node.names)
    return mods


def _violations(package: str, forbidden_roots: set[str]) -> list[str]:
    bad = []
    for f in sorted((ROOT / package).rglob("*.py")):
        for m in _imports(f):
            if m.split(".")[0] in forbidden_roots:
                bad.append(f"{f.relative_to(ROOT)} imports {m}")
    return bad


def test_backend_layers_do_not_import_ui_frameworks():
    bad = []
    for pkg in ("services", "core", "db"):
        bad += _violations(pkg, UI_FRAMEWORKS)
    assert not bad, "\n".join(bad)


def test_ui_does_not_touch_database_layer():
    assert not _violations("ui", {"db"}), "ui/ phải gọi services/, không import db/"


def test_no_upward_imports():
    bad = _violations("services", {"ui"}) + _violations("core", {"ui", "services"}) + _violations("db", {"ui", "services"})
    # db/ chỉ được dùng helper thuần core.timeutil (giờ GMT+7), không phụ thuộc phần còn lại của core/
    for f in sorted((ROOT / "db").rglob("*.py")):
        bad += [f"{f.relative_to(ROOT)} imports {m}" for m in _imports(f)
                if m.split(".")[0] == "core" and m != "core.timeutil" and m != "core"]
    assert not bad, "\n".join(bad)
