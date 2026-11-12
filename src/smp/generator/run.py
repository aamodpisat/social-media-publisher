from __future__ import annotations

from pathlib import Path
from typing import List

from smp.config import get_settings
from smp.generator.templates import iter_templates, resolve_media
from smp.llm import complete
from smp.publisher.media import validate_media
from smp.scheduler.days import iso_week_id
from smp.store import drafts as draft_store
from smp.store.drafts import Draft

SYSTEM = """You write social captions for Instagram and Facebook.
Return only the caption text. No quotes, no markdown fences, no hashtags dump unless the brief asks.
Never mention API keys, tokens, environment variables, or internal file paths.
Keep Instagram captions under 2200 characters. Include a clear CTA when the brief has one.
"""


def _platforms(meta: dict) -> List[str]:
    raw = meta.get("platforms") or ["instagram", "facebook"]
    if isinstance(raw, str):
        raw = [raw]
    return [str(p).lower() for p in raw]


def generate_week(*, force: bool = False) -> List[Draft]:
    settings = get_settings()
    if not settings.llm_ready():
        raise RuntimeError("Set LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL in .env before generating.")

    batch_id = iso_week_id()
    if not force and draft_store.week_has_open_work(batch_id):
        return draft_store.batch_items(batch_id)

    created: List[Draft] = []
    for content_type, path, meta, body in iter_templates():
        media = resolve_media(content_type, meta, path)
        validate_media(content_type, media)
        platforms = _platforms(meta)
        title = str(meta.get("title") or path.stem)
        user = (
            f"Content type: {content_type}\n"
            f"Title: {title}\n"
            f"CTA: {meta.get('cta', '')}\n"
            f"Hashtags to consider: {meta.get('hashtags', [])}\n"
            f"Template notes:\n{body}\n"
        )
        caption = complete(SYSTEM, user)
        created.append(
            draft_store.create_draft(
                batch_id=batch_id,
                content_type=content_type,
                platforms=platforms,
                caption=caption,
                media_paths=media,
                title=title,
                source_template=str(path.relative_to(settings.templates_dir)),
            )
        )
    return created
