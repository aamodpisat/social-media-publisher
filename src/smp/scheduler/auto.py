from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from smp.config import get_settings
from smp.content.fingerprint import file_sha256
from smp.generator.run import SYSTEM
from smp.llm import complete_with_media
from smp.publisher.media import validate_media
from smp.scheduler.days import iso_week_id
from smp.store import drafts as draft_store, published as published_store
from smp.store.drafts import Draft
from smp.publisher.meta import PublishError, publish_draft

FOLDERS = {"Posts": "posts", "Reels": "reels", "Story": "story"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v"}


def _candidates(root: Path) -> list[tuple[Path, str]]:
    found = []
    for folder, kind in FOLDERS.items():
        directory = root / folder
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.name.startswith(".") or not path.is_file():
                continue
            if path.suffix.lower() not in IMAGE_EXT | VIDEO_EXT:
                continue
            if time.time() - path.stat().st_mtime < 120:
                continue  # avoid files still being copied
            found.append((path, kind))
    return sorted(found, key=lambda pair: (pair[0].stat().st_mtime, str(pair[0]).casefold()))


def _existing_for_hash(media_hash: str) -> Optional[Draft]:
    for item in draft_store.load_all():
        if item.media_hash == media_hash:
            return item
    return None


def next_media() -> Optional[tuple[Path, str]]:
    """Return the next stable media item that has not successfully published."""
    settings = get_settings()
    published_hashes = {r.media_hash for r in published_store.load_all() if r.status == "published" and r.media_hash}
    for path, kind in _candidates(settings.media_root):
        digest = file_sha256(path)
        if digest in published_hashes:
            continue
        old = _existing_for_hash(digest)
        if old and (old.status == "published" or old.ig_media_id or old.status == "rejected"):
            continue
        return path, kind
    return None


def publish_one_new(*, media_path: Path | None = None, caption: str = "") -> Optional[Draft]:
    """Publish no more than one new media item; called by a local weekend schedule."""
    settings = get_settings()
    if not caption and not settings.llm_ready():
        raise RuntimeError("Caption generation is not configured in .env.")
    if not settings.meta_ready():
        raise RuntimeError("Meta publishing is not configured in .env.")
    if not settings.contentstack_ready():
        raise RuntimeError("Contentstack upload is not configured in .env.")

    candidates = _candidates(settings.media_root)
    if media_path is not None:
        path_resolved = media_path.expanduser().resolve()
        root = settings.media_root.resolve()
        if not path_resolved.is_relative_to(root):
            raise ValueError("Selected media must be inside MEDIA_ROOT.")
        candidates = [(p,k) for p,k in candidates if p.resolve() == path_resolved]
        if not candidates:
            raise ValueError("Selected media is missing, unsupported, or still being copied.")
    for path, kind in candidates:
        digest = file_sha256(path)
        if any(r.media_hash == digest and r.status == "published" for r in published_store.load_all()):
            continue
        old = _existing_for_hash(digest)
        if old and (old.status == "published" or old.ig_media_id):
            continue  # an uncertain/partial publish must be reconciled manually, never reposted
        if old and old.status == "rejected":
            continue
        if old and old.status == "failed":
            old.status = "approved"
            old.error = ""
            draft = draft_store.save(old)
        else:
            validate_media(kind, [path])
            prompt = (
                "Create a caption for Aamod P. Pisat Photography, an award-winning wedding photographer. "
                "Brand line: Capturing the real emotions. Write naturally and specifically from what is visible. "
                "Do not invent names, locations, dates, or shoot details. Include a direct DM/enquiry/booking CTA, "
                "a small relevant set of hashtags, and keep it concise. This is for an Instagram " + kind + ".\n"
                f"Filename for context only: {path.stem}"
            )
            final_caption = caption.strip() or complete_with_media(SYSTEM, prompt, path)
            draft = draft_store.create_draft(
                batch_id=iso_week_id(), content_type=kind, platforms=["instagram"], caption=final_caption,
                media_paths=[path], title=path.stem, source_template="automatic-folder-scan",
            )
            draft.status = "approved"
            draft = draft_store.save(draft)
        try:
            result = publish_draft(draft)
        except Exception as exc:
            draft.status = "failed"
            draft.error = str(exc)
            draft_store.save(draft)
            raise
        return result
    return None
