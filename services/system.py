"""
services/system.py — điều khiển vòng đời ứng dụng (tắt app) cho nút "Tắt ứng dụng" trên giao diện.

Chỉ cho phép tắt khi yêu cầu đến từ CHÍNH máy đang chạy app: không phải kết nối từ xa qua link chia sẻ
gradio.live hay HOST=0.0.0.0 (những kết nối đó cũng có thể xuất hiện với địa chỉ 127.0.0.1 khi đi qua
đường hầm/proxy, nên còn kiểm tra các header chuyển tiếp).
"""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Mapping

logger = logging.getLogger(__name__)

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_FORWARD_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded")


def is_local_request(client_host: str | None, headers: Mapping[str, str] | None = None) -> bool:
    """True nếu yêu cầu đến trực tiếp từ máy chạy app (loopback và không qua proxy/đường hầm)."""
    if (client_host or "").strip().lower() not in _LOOPBACK:
        return False
    lowered = {str(k).lower() for k in (headers or {})}
    return not any(h in lowered for h in _FORWARD_HEADERS)


def _hard_exit() -> None:
    """Dừng scheduler (không chờ job đang chạy), xả log rồi thoát tiến trình."""
    try:
        from core import scheduler as _sched

        if _sched._scheduler is not None:
            _sched._scheduler.shutdown(wait=False)
    except Exception as e:  # không để lỗi dọn dẹp chặn việc tắt
        logger.warning(f"Không dừng được scheduler gọn gàng: {e}")
    logging.shutdown()
    os._exit(0)


def schedule_shutdown(delay: float = 1.0, exit_fn: Callable[[], None] | None = None) -> None:
    """Hẹn tắt ứng dụng sau `delay` giây (đủ thời gian để trả phản hồi cho trình duyệt trước khi tiến trình thoát)."""
    logger.info(f"Nhận yêu cầu tắt ứng dụng — sẽ thoát sau {delay}s")
    timer = threading.Timer(delay, exit_fn or _hard_exit)
    timer.daemon = True
    timer.start()
