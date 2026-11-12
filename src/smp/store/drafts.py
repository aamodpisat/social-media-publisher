from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from smp.config import get_settings
from smp.content.fingerprint import file_sha256, fingerprint as make_fingerprint
from smp.store import published as published_store

STATUSES = ("draft", "approved", "rejected", "duplicate_blocked", "published", "failed")


@dataclass
class Draft:
    id: str
    batch_id: str
    content_type: str
    platforms: List[str]
    caption: str
    media_paths: List[str]
    fingerprint: str
    status: str = "draft"
    title: str = ""
    source_template: str = ""
    error: str = ""
    ig_media_id: Optional[str] = None
    fb_post_id: Optional[str] = None
    contentstack_asset_url: Optional[str] = None
    media_hash: str = ""
    updated_at: str = ""


def _path() -> Path:
    return get_settings().data_dir / "drafts.json"


def load_all() -> List[Draft]:
    path = _path()
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Draft(**item) for item in raw]


def _write(drafts: List[Draft]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(d) for d in drafts], indent=2) + "\n", encoding="utf-8")


def get(draft_id: str) -> Optional[Draft]:
    for item in load_all():
        if item.id == draft_id:
            return item
    return None


def batch_items(batch_id: str) -> List[Draft]:
    return [d for d in load_all() if d.batch_id == batch_id]


def list_batch_ids() -> List[str]:
    seen = []
    for item in load_all():
        if item.batch_id not in seen:
            seen.append(item.batch_id)
    return seen


def save(draft: Draft) -> Draft:
    draft.updated_at = datetime.now(timezone.utc).isoformat()
    drafts = load_all()
    for i, existing in enumerate(drafts):
        if existing.id == draft.id:
            drafts[i] = draft
            _write(drafts)
            return draft
    drafts.append(draft)
    _write(drafts)
    return draft


def create_draft(
    *,
    batch_id: str,
    content_type: str,
    platforms: List[str],
    caption: str,
    media_paths: List[Path],
    title: str,
    source_template: str,
) -> Draft:
    fp = make_fingerprint(content_type, platforms, caption, media_paths)
    status = "duplicate_blocked" if published_store.is_posted(fp) else "draft"
    draft = Draft(
        id=str(uuid.uuid4()),
        batch_id=batch_id,
        content_type=content_type,
        platforms=platforms,
        caption=caption,
        media_paths=[str(p) for p in media_paths],
        fingerprint=fp,
        media_hash=file_sha256(media_paths[0]),
        status=status,
        title=title,
        source_template=source_template,
    )
    return save(draft)


def week_has_open_work(batch_id: str) -> bool:
    return any(d.status in {"draft", "approved"} for d in batch_items(batch_id))


def update_caption(draft_id: str, caption: str) -> Draft:
    draft = get(draft_id)
    if not draft:
        raise KeyError(draft_id)
    if draft.status not in {"draft", "approved"}:
        raise ValueError("Can only edit draft or approved items before publish.")
    draft.caption = caption
    paths = [Path(p) for p in draft.media_paths]
    draft.fingerprint = make_fingerprint(draft.content_type, draft.platforms, caption, paths)
    if published_store.is_posted(draft.fingerprint):
        draft.status = "duplicate_blocked"
        draft.error = "This caption + media was already published."
    elif draft.status == "duplicate_blocked":
        draft.status = "draft"
        draft.error = ""
    return save(draft)


def exclude(draft_id: str) -> Draft:
    draft = get(draft_id)
    if not draft:
        raise KeyError(draft_id)
    if draft.status == "published":
        raise ValueError("Cannot exclude a published item.")
    draft.status = "rejected"
    return save(draft)


def approve_batch(batch_id: str) -> List[Draft]:
    """One-click approve for the week's remaining drafts. Idempotent."""
    updated: List[Draft] = []
    for draft in batch_items(batch_id):
        if draft.status == "rejected":
            updated.append(draft)
            continue
        if draft.status in {"published", "duplicate_blocked", "failed"}:
            updated.append(draft)
            continue
        paths = [Path(p) for p in draft.media_paths]
        draft.fingerprint = make_fingerprint(
            draft.content_type, draft.platforms, draft.caption, paths
        )
        if published_store.is_posted(draft.fingerprint):
            draft.status = "duplicate_blocked"
            draft.error = "Already published — skipped from batch approve."
        else:
            draft.status = "approved"
            draft.error = ""
        updated.append(save(draft))
    return updated
