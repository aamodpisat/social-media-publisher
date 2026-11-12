from __future__ import annotations

from typing import Iterable, List, Sequence

from smp.config import WEEKDAYS


def normalize_days(days: Iterable[str]) -> List[str]:
    seen = []
    for raw in days:
        d = raw.strip().lower()[:3]
        if d not in WEEKDAYS:
            raise ValueError(f"Unknown weekday: {raw}")
        if d not in seen:
            seen.append(d)
    return sorted(seen, key=WEEKDAYS.index)


def resolve_posting_days(ui_days: Sequence[str] | None, env_days: Iterable[str]) -> List[str]:
    """UI selection wins when non-empty; otherwise .env; otherwise tue,wed,thu."""
    if ui_days:
        return normalize_days(ui_days)
    env = list(env_days)
    if env:
        return normalize_days(env)
    return ["tue", "wed", "thu"]
