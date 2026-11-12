from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from smp.config import get_settings


@dataclass
class AppUiSettings:
    posting_days: List[str] = field(default_factory=list)

    def to_public(self) -> dict:
        return {"postingDays": self.posting_days}


def _path() -> Path:
    return get_settings().data_dir / "settings.json"


def load_settings() -> AppUiSettings:
    path = _path()
    if not path.is_file():
        return AppUiSettings()
    raw = json.loads(path.read_text(encoding="utf-8"))
    days = raw.get("postingDays") or raw.get("posting_days") or []
    if not isinstance(days, list):
        days = []
    return AppUiSettings(posting_days=[str(d) for d in days])


def save_settings(settings: AppUiSettings) -> AppUiSettings:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings.to_public(), indent=2) + "\n", encoding="utf-8")
    return settings
