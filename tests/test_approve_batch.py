from pathlib import Path

from smp.store import drafts as draft_store
from smp.store import published as published_store
from smp.store.published import PublishedRecord


def _make_media(tmp_app: Path) -> Path:
    path = tmp_app / "templates" / "posts" / "assets" / "p.jpg"
    path.write_bytes(b"jpeg-bytes")
    return path


def test_approve_batch_approves_drafts(tmp_app):
    media = _make_media(tmp_app)
    a = draft_store.create_draft(
        batch_id="2026-W37",
        content_type="posts",
        platforms=["instagram"],
        caption="one",
        media_paths=[media],
        title="a",
        source_template="posts/a.md",
    )
    b = draft_store.create_draft(
        batch_id="2026-W37",
        content_type="story",
        platforms=["instagram"],
        caption="two",
        media_paths=[media],
        title="b",
        source_template="story/b.md",
    )
    draft_store.exclude(b.id)
    draft_store.approve_batch("2026-W37")
    assert draft_store.get(a.id).status == "approved"
    assert draft_store.get(b.id).status == "rejected"


def test_duplicate_not_approved(tmp_app):
    media = _make_media(tmp_app)
    draft = draft_store.create_draft(
        batch_id="2026-W37",
        content_type="posts",
        platforms=["instagram"],
        caption="same",
        media_paths=[media],
        title="a",
        source_template="posts/a.md",
    )
    published_store.upsert(
        PublishedRecord(
            fingerprint=draft.fingerprint,
            content_type="posts",
            platforms=["instagram"],
            caption="same",
            status="published",
        )
    )
    draft.status = "draft"
    draft_store.save(draft)
    draft_store.approve_batch("2026-W37")
    assert draft_store.get(draft.id).status == "duplicate_blocked"


def test_second_approve_is_noop(tmp_app):
    media = _make_media(tmp_app)
    draft = draft_store.create_draft(
        batch_id="2026-W37",
        content_type="posts",
        platforms=["instagram"],
        caption="once",
        media_paths=[media],
        title="a",
        source_template="posts/a.md",
    )
    draft_store.approve_batch("2026-W37")
    draft_store.approve_batch("2026-W37")
    assert draft_store.get(draft.id).status == "approved"
    assert len(draft_store.batch_items("2026-W37")) == 1
