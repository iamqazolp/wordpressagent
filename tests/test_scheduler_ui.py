import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timedelta
from ui.tab_create import (
    parse_scheduled_datetime,
    format_time_preview,
    set_quick_schedule,
    schedule_post_ui,
)


def test_parse_scheduled_datetime():
    now = datetime.now()
    # 1. Datetime object
    assert parse_scheduled_datetime(now) == now

    # 2. Timestamp float/int
    ts = now.timestamp()
    parsed_ts = parse_scheduled_datetime(ts)
    assert abs((parsed_ts - now).total_seconds()) < 1.0

    # 3. String formats
    test_str = "2026-10-15 14:30:00"
    parsed_str = parse_scheduled_datetime(test_str)
    assert parsed_str.year == 2026 and parsed_str.month == 10 and parsed_str.hour == 14

    test_str2 = "2026-10-15 14:30"
    parsed_str2 = parse_scheduled_datetime(test_str2)
    assert parsed_str2.minute == 30

    test_str3 = "15/10/2026 14:30"
    parsed_str3 = parse_scheduled_datetime(test_str3)
    assert parsed_str3.day == 15 and parsed_str3.month == 10

    # 4. None and empty
    assert parse_scheduled_datetime(None) is None
    assert parse_scheduled_datetime("") is None
    assert parse_scheduled_datetime("invalid string") is None


def test_format_time_preview():
    # 1. Empty/None
    assert "Chưa chọn" in format_time_preview(None)

    # 2. Past time
    past = datetime.now() - timedelta(minutes=10)
    assert "Thời gian đã qua" in format_time_preview(past)

    # 3. Future time
    future = datetime.now() + timedelta(hours=2, minutes=15)
    preview = format_time_preview(future)
    assert "Dự kiến đăng vào" in preview
    assert "sau khoảng" in preview


def test_set_quick_schedule():
    now = datetime.now()
    # Test +30m
    dt_30m, preview_30m = set_quick_schedule("30m")
    diff_30m = (dt_30m - now).total_seconds() / 60
    assert 29 <= diff_30m <= 31
    assert "Dự kiến đăng vào" in preview_30m

    # Test +1h
    dt_1h, _ = set_quick_schedule("1h")
    diff_1h = (dt_1h - now).total_seconds() / 3600
    assert 0.95 <= diff_1h <= 1.05

    # Test tomorrow 8am
    dt_8am, _ = set_quick_schedule("tomorrow_8am")
    assert dt_8am.hour == 8 and dt_8am.minute == 0
    assert dt_8am > now


def test_schedule_post_ui_validations():
    # 1. No articles
    res1 = schedule_post_ui(None, [], "publish", "post")
    assert "Chưa có nội dung" in res1

    # 2. Past time
    past = datetime.now() - timedelta(minutes=5)
    articles = {"site1": {"title": "Test Title", "raw_html": "<p>Content</p>"}}
    res2 = schedule_post_ui(articles, [], "publish", "post", scheduled_datetime=past)
    assert "phải ở trong tương lai" in res2


if __name__ == "__main__":
    print("Running scheduler UI tests...")
    test_parse_scheduled_datetime()
    print("✓ test_parse_scheduled_datetime passed")
    test_format_time_preview()
    print("✓ test_format_time_preview passed")
    test_set_quick_schedule()
    print("✓ test_set_quick_schedule passed")
    test_schedule_post_ui_validations()
    print("✓ test_schedule_post_ui_validations passed")
    print("\n🎉 ALL SCHEDULER UI TESTS PASSED!")
