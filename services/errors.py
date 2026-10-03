"""Lỗi nghiệp vụ "dự kiến được" (dữ liệu sai, trùng tên, không tìm thấy...).

Service raise ServiceError(thông_điệp_tiếng_Việt); lớp giao diện/API bắt lại và hiển thị
(ui: "❌ {message}"; api: HTTP 4xx). Lỗi bất ngờ vẫn là Exception thường.
"""
from __future__ import annotations


class ServiceError(Exception):
    """Lỗi nghiệp vụ có thông điệp thân thiện với người dùng."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class PublishError(ServiceError):
    """Đăng lên WordPress thất bại (khác với lỗi dữ liệu đầu vào: không tìm thấy bài, thiếu cấu hình...)."""
