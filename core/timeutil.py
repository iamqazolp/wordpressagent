"""Tiện ích thời gian: toàn bộ hệ thống dùng giờ Việt Nam (GMT+7).

Quy ước: DB lưu datetime *naive* theo giờ tường (wall-clock) GMT+7.
Dùng offset cố định (Việt Nam không có DST) nên không cần tzdata.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

VN_TZ = timezone(timedelta(hours=7), "GMT+7")
TZ_LABEL = "GMT+7"
# Tên IANA dùng cho thư viện cần tên múi giờ (APScheduler, gr.DateTime)
TZ_NAME = "Asia/Ho_Chi_Minh"


def now_vn() -> datetime:
    """Giờ hiện tại ở GMT+7, dạng naive (để lưu/so sánh với dữ liệu DB)."""
    return datetime.now(VN_TZ).replace(tzinfo=None)


def to_vn_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Chuẩn hóa datetime về naive GMT+7. Naive được coi là đã ở GMT+7."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(VN_TZ).replace(tzinfo=None)


def fmt_vn(dt: Optional[datetime], fmt: str = "%d/%m/%Y %H:%M", empty: str = "-") -> str:
    """Định dạng datetime (đã ở GMT+7) để hiển thị."""
    dt = to_vn_naive(dt)
    return dt.strftime(fmt) if dt else empty


def utc_iso_to_vn(value: Optional[str], fmt: str = "%d/%m/%Y %H:%M", empty: str = "-") -> str:
    """
    Chuỗi ISO theo UTC (vd '2026-10-04T09:30:00' từ trường *_gmt của WordPress, không có hậu tố múi giờ)
    -> giờ GMT+7 để hiển thị. Chuỗi rỗng/không đọc được -> `empty`.
    """
    if not value:
        return empty
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return empty
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return fmt_vn(dt, fmt, empty)


def vn_to_utc_iso(dt: Optional[datetime]) -> Optional[str]:
    """
    Chuyển datetime naive GMT+7 sang chuỗi ISO UTC (YYYY-MM-DDTHH:MM:SS) không có hậu tố múi giờ
    cho các trường *_gmt của WordPress REST API (vd date_gmt, date_created_gmt).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S")
