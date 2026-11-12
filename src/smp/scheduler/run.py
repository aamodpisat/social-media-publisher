from __future__ import annotations

from typing import List

from smp.publisher.meta import PublishError, publish_draft
from smp.scheduler.days import is_posting_day
from smp.store import drafts as draft_store
from smp.store import published as published_store
from smp.store.drafts import Draft


def due_drafts() -> List[Draft]:
    items = [d for d in draft_store.load_all() if d.status == "approved"]
    items.sort(key=lambda d: (d.batch_id, d.updated_at, d.id))
    return items


def publish_due() -> List[Draft]:
    if not is_posting_day():
        return []
    published: List[Draft] = []
    for draft in due_drafts():
        if published_store.is_posted(draft.fingerprint) and published_store.fingerprints()[draft.fingerprint].status == "published":
            draft.status = "duplicate_blocked"
            draft.error = "Already published."
            draft_store.save(draft)
            continue
        published.append(publish_draft(draft))
    return published
