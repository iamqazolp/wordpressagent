r"""
Sao lưu / khôi phục dữ liệu WordPress Agent.

  python tools/backup.py                   # tạo file backups/wordpress-agent-backup-<ngày giờ>.zip
  python tools/backup.py --to D:\Sao_luu   # đặt file sao lưu vào thư mục khác (ổ ngoài, cloud...)
  python tools/backup.py restore <file.zip># khôi phục (TẮT ứng dụng trước)

File .zip chứa ENCRYPTION_KEY và API key: hãy cất ở nơi kín, đừng gửi qua chat/email công khai.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import backup  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    ap.add_argument("--to", help="thư mục lưu file sao lưu (mặc định: ./backups)")
    r = sub.add_parser("restore", help="khôi phục từ file .zip")
    r.add_argument("file")
    r.add_argument("--yes", action="store_true", help="không hỏi xác nhận")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "restore":
            if not args.yes:
                print("⚠  Khôi phục sẽ GHI ĐÈ dữ liệu hiện tại (có tạo bản an toàn trước). Hãy chắc chắn ứng dụng đang TẮT.")
                if input("Gõ 'yes' để tiếp tục: ").strip().lower() != "yes":
                    print("Đã huỷ.")
                    return 1
            safety = backup.restore_full_backup(Path(args.file))
            print(f"✓ Đã khôi phục. Bản an toàn của dữ liệu trước đó: {safety}")
        else:
            out = backup.create_full_backup(Path(args.to) if args.to else None)
            print(f"✓ Đã tạo bản sao lưu: {out}")
            print("  File này chứa ENCRYPTION_KEY và API key — hãy cất ở nơi kín.")
    except backup.BackupError as e:
        print(f"✗ {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
