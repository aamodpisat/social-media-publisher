from datetime import datetime
from zoneinfo import ZoneInfo

from smp.scheduler import resolve_posting_days
from smp.scheduler.days import is_posting_day, today_weekday


def test_ui_overrides_env():
    assert resolve_posting_days(["mon"], ["tue", "wed", "thu"]) == ["mon"]


def test_empty_ui_uses_env():
    assert resolve_posting_days([], ["fri"]) == ["fri"]
    assert resolve_posting_days(None, ["fri"]) == ["fri"]


def test_empty_both_defaults_midweek():
    assert resolve_posting_days([], []) == ["tue", "wed", "thu"]


def test_is_posting_day_kolkata(tmp_app, monkeypatch):
    tz = ZoneInfo("Asia/Kolkata")
    wednesday = datetime(2026, 9, 9, 11, 0, tzinfo=tz)
    friday = datetime(2026, 9, 11, 11, 0, tzinfo=tz)
    assert today_weekday(wednesday) == "wed"
    assert is_posting_day(wednesday, ui_days=["tue", "wed", "thu"])
    assert not is_posting_day(friday, ui_days=["tue", "wed", "thu"])
