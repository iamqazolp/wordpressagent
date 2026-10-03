import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timedelta, timezone

import gradio as gr

from core.timeutil import TZ_NAME, VN_TZ, fmt_vn, now_vn, to_vn_naive
from ui.tab_create import parse_scheduled_datetime


def test_now_vn_is_naive_and_utc_plus_7():
    n = now_vn()
    assert n.tzinfo is None
    utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((n - utc_naive) - timedelta(hours=7)) < timedelta(seconds=5)


def test_to_vn_naive_converts_aware_and_keeps_naive():
    utc = datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)
    assert to_vn_naive(utc) == datetime(2026, 1, 2, 3, 0)
    naive = datetime(2026, 1, 1, 20, 0)
    assert to_vn_naive(naive) == naive
    assert to_vn_naive(None) is None


def test_fmt_vn():
    assert fmt_vn(datetime(2026, 1, 2, 3, 4)) == "02/01/2026 03:04"
    assert fmt_vn(None) == "-"
    assert fmt_vn(datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc), "%H:%M") == "03:00"


def test_picker_with_timezone_roundtrips_to_vn_wall_clock():
    picker = gr.DateTime(type="datetime", include_time=True, timezone=TZ_NAME)
    got = picker.preprocess("2026-12-14 12:00:00")
    # Gradio gắn tzinfo VN → ta phải quy về đúng giờ tường 12:00
    assert parse_scheduled_datetime(got) == datetime(2026, 12, 14, 12, 0)


def test_parse_timestamp_uses_vn_zone():
    ts = datetime(2026, 12, 14, 5, 0, tzinfo=timezone.utc).timestamp()
    assert parse_scheduled_datetime(ts) == datetime(2026, 12, 14, 12, 0)
