from __future__ import annotations

from datetime import datetime
from typing import List
from zoneinfo import ZoneInfo

from smp.config import WEEKDAYS, get_settings
from smp.scheduler import resolve_posting_days
from smp.store.settings import load_settings


def today_weekday(now: datetime | None = None) -> str:
    settings = get_settings()
    tz = ZoneInfo(settings.posting_timezone)
    current = now.astimezone(tz) if now else datetime.now(tz)
    return WEEKDAYS[current.weekday()]


def is_posting_day(now: datetime | None = None, ui_days: List[str] | None = None) -> bool:
    settings = get_settings()
    persisted = load_settings()
    days = resolve_posting_days(
        ui_days if ui_days is not None else persisted.posting_days,
        settings.env_posting_days(),
    )
    return today_weekday(now) in days


def iso_week_id(now: datetime | None = None) -> str:
    settings = get_settings()
    tz = ZoneInfo(settings.posting_timezone)
    current = now.astimezone(tz) if now else datetime.now(tz)
    iso = current.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"
