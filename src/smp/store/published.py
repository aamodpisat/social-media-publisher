from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from smp.config import get_settings


@dataclass
class PublishedRecord:
    fingerprint: str
    content_type: str
    platforms: List[str]
    caption: str
    ig_media_id: Optional[str] = None
    fb_post_id: Optional[str] = None
    posted_at: str = ""
    status: str = "published"  # published | partial
    media_hash: str = ""


def _path() -> Path:
    return get_settings().data_dir / "published.json"


def load_all() -> List[PublishedRecord]:
    path = _path()
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [PublishedRecord(**item) for item in raw]


def _write(records: List[PublishedRecord]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(r) for r in records], indent=2) + "\n",
        encoding="utf-8",
    )


def fingerprints() -> Dict[str, PublishedRecord]:
    return {r.fingerprint: r for r in load_all()}


def is_posted(fingerprint: str) -> bool:
    rec = fingerprints().get(fingerprint)
    return rec is not None and rec.status == "published"


def upsert(record: PublishedRecord) -> PublishedRecord:
    if not record.posted_at:
        record.posted_at = datetime.now(timezone.utc).isoformat()
    records = load_all()
    replaced = False
    for i, existing in enumerate(records):
        if existing.fingerprint == record.fingerprint:
            records[i] = record
            replaced = True
            break
    if not replaced:
        records.append(record)
    _write(records)
    return record
