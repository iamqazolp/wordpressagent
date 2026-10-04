"""
Đóng gói bản phát hành cho khách: dist/wordpress-agent-<phiên bản>.zip

Chỉ lấy file ĐÃ COMMIT (git archive) nên không bao giờ lẫn .env, data/, config/sites.json, khoá hay bản sao lưu.
Loại thêm các file chỉ dành cho lập trình viên (tests, kế hoạch, công cụ dev). File .bat được đổi sang CRLF.

  python tools/make_release.py            # dùng HEAD
  python tools/make_release.py --ref v1.0.0
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Đường dẫn (so với gốc dự án) không đưa vào bản phát hành. Mục kết thúc bằng "/" là cả thư mục.
EXCLUDE = (
    "tests/", "tools/wiring_snapshot.py", "tools/make_release.py", "PLAN.MD", "ARCHITECTURE.md",
    "requirements-dev.txt", "pytest.ini", ".gitattributes", ".gitignore",
)
# Bắt buộc phải có trong bản phát hành (kiểm tra để không giao thiếu)
REQUIRED = ("app.py", "requirements.txt", "requirements.lock", "install.sh", "install.bat", "run.sh", "run.bat",
            ".env.example", "README.md", "VERSION", "core/wp_client.py", "ui/main_ui.py", "tools/backup.py", "tools/init_env.py")
FORBIDDEN_PREFIXES = ("data/", "config/sites.json", ".env", "backups/", ".venv/", "dist/")


def _excluded(name: str, prefix: str) -> bool:
    rel = name[len(prefix):]
    return any(rel == e or (e.endswith("/") and rel.startswith(e)) for e in EXCLUDE)


def build(ref: str = "HEAD", out_dir: Path | None = None) -> Path:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "VERSION").exists() else "dev"
    name = f"wordpress-agent-{version}"
    prefix = name + "/"
    out_dir = out_dir or ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = subprocess.run(["git", "archive", "--format=zip", f"--prefix={prefix}", ref], cwd=ROOT, check=True, capture_output=True).stdout

    out = out_dir / f"{name}.zip"
    kept: list[str] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            if info.is_dir() or _excluded(info.filename, prefix):
                continue
            data = src.read(info)
            if info.filename.endswith(".bat"):
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            dst.writestr(info, data)   # giữ nguyên quyền thực thi (.sh)
            kept.append(info.filename[len(prefix):])

    missing = [r for r in REQUIRED if r not in kept]
    leaked = [k for k in kept if k.startswith(FORBIDDEN_PREFIXES)]
    if missing or leaked:
        out.unlink(missing_ok=True)
        raise SystemExit(f"✗ Bản phát hành không hợp lệ. Thiếu: {missing or '-'} · Lọt vào: {leaked or '-'}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="HEAD")
    args = ap.parse_args()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty and args.ref == "HEAD":
        print("⚠  Có thay đổi chưa commit — bản phát hành chỉ gồm phần ĐÃ commit.", file=sys.stderr)
    path = build(args.ref)
    print(f"✓ {path} ({path.stat().st_size // 1024} KB)")
