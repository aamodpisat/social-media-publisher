from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Tuple

import httpx

from smp.config import get_settings
from smp.publisher.contentstack import upload_asset
from smp.redact import redact, redact_text
from smp.store.drafts import Draft

GRAPH = "https://graph.facebook.com"


class PublishError(RuntimeError):
    pass


def _client() -> Tuple[httpx.Client, str, str, str]:
    settings = get_settings()
    if not settings.meta_ready():
        raise PublishError(
            "Meta is not configured. Set META_PAGE_ID, META_IG_USER_ID, and META_PAGE_ACCESS_TOKEN."
        )
    client = httpx.Client(timeout=60.0)
    return client, settings.meta_graph_version, settings.meta_page_id, settings.meta_ig_user_id


def _token() -> str:
    return get_settings().meta_page_access_token


def _graph_url(version: str, path: str) -> str:
    return f"{GRAPH}/{version}/{path.lstrip('/')}"


def _request(client: httpx.Client, method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
    params = dict(kwargs.pop("params", {}) or {})
    params["access_token"] = _token()
    try:
        response = client.request(method, url, params=params, **kwargs)
        data = response.json() if response.content else {}
    except httpx.HTTPError as exc:
        raise PublishError(redact_text(str(exc))) from None
    if response.status_code >= 400 or (isinstance(data, dict) and data.get("error")):
        raise PublishError(redact(data.get("error") if isinstance(data, dict) else data) or redact_text(response.text))
    if not isinstance(data, dict):
        raise PublishError("Unexpected Graph API response.")
    return data


def _wait_ig_container(client: httpx.Client, version: str, creation_id: str) -> None:
    url = _graph_url(version, creation_id)
    for _ in range(20):
        data = _request(client, "GET", url, params={"fields": "status_code,status"})
        code = (data.get("status_code") or "").upper()
        if code in {"FINISHED", "PUBLISHED"}:
            return
        if code in {"ERROR", "EXPIRED"}:
            raise PublishError(redact(data))
        time.sleep(3)
    raise PublishError("Instagram media container was not ready in time.")


def instagram_container_payload(draft: Draft, media_url: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"caption": draft.caption}
    suffix = Path(draft.media_paths[0]).suffix.lower() if draft.media_paths else ""
    is_video = suffix in {".mp4", ".mov", ".m4v"}
    if draft.content_type == "reels":
        payload["media_type"] = "REELS"
        payload["video_url"] = media_url
        payload["share_to_feed"] = "true"
    elif draft.content_type == "story":
        payload["media_type"] = "STORIES"
        payload["video_url" if is_video else "image_url"] = media_url
    elif is_video:
        payload["media_type"] = "REELS"
        payload["video_url"] = media_url
    else:
        payload["image_url"] = media_url
    return payload


def _publish_instagram(client: httpx.Client, version: str, ig_user_id: str, draft: Draft, media_url: str) -> str:
    payload = instagram_container_payload(draft, media_url)

    create = _request(client, "POST", _graph_url(version, f"{ig_user_id}/media"), params=payload)
    creation_id = create.get("id")
    if not creation_id:
        raise PublishError("Instagram did not return a media container id.")
    _wait_ig_container(client, version, creation_id)
    published = _request(
        client,
        "POST",
        _graph_url(version, f"{ig_user_id}/media_publish"),
        params={"creation_id": creation_id},
    )
    media_id = published.get("id")
    if not media_id:
        raise PublishError("Instagram publish did not return a media id.")
    return str(media_id)


def _publish_facebook(client: httpx.Client, version: str, page_id: str, draft: Draft, media_url: str) -> str:
    suffix = Path(draft.media_paths[0]).suffix.lower()
    is_video = suffix in {".mp4", ".mov", ".m4v"}

    if draft.content_type == "story":
        if is_video:
            data = _request(
                client,
                "POST",
                _graph_url(version, f"{page_id}/video_stories"),
                params={"upload_phase": "start"},
            )
            return str(data.get("video_id") or data.get("id") or "")
        photo = _request(
            client,
            "POST",
            _graph_url(version, f"{page_id}/photos"),
            params={"url": media_url, "published": "false"},
        )
        photo_id = photo.get("id")
        data = _request(
            client,
            "POST",
            _graph_url(version, f"{page_id}/photo_stories"),
            params={"photo_id": photo_id},
        )
        return str(data.get("post_id") or data.get("id") or photo_id)

    if is_video or draft.content_type == "reels":
        data = _request(
            client,
            "POST",
            _graph_url(version, f"{page_id}/videos"),
            params={"file_url": media_url, "description": draft.caption},
        )
        return str(data.get("id"))

    data = _request(
        client,
        "POST",
        _graph_url(version, f"{page_id}/photos"),
        params={"url": media_url, "caption": draft.caption},
    )
    return str(data.get("post_id") or data.get("id"))


def publish_draft(draft: Draft) -> Draft:
    """Publish one approved draft. Partial success is recorded per destination."""
    from smp.store import drafts as draft_store
    from smp.store import published as published_store
    from smp.store.published import PublishedRecord

    if draft.status != "approved":
        raise PublishError("Only approved drafts can be published.")
    if published_store.is_posted(draft.fingerprint):
        draft.status = "duplicate_blocked"
        draft.error = "Fingerprint already published."
        return draft_store.save(draft)

    media_path = Path(draft.media_paths[0])
    media_url = draft.contentstack_asset_url or upload_asset(media_path)
    draft.contentstack_asset_url = media_url
    draft_store.save(draft)
    client, version, page_id, ig_user_id = _client()
    errors = []
    try:
        if "instagram" in draft.platforms and not draft.ig_media_id:
            try:
                draft.ig_media_id = _publish_instagram(client, version, ig_user_id, draft, media_url)
            except PublishError as exc:
                errors.append(f"instagram: {exc}")
        # Instagram's connected Meta sharing setting is responsible for Facebook cross-posting.
    finally:
        client.close()

    needed_ig = "instagram" in draft.platforms
    needed_fb = False
    ig_ok = (not needed_ig) or bool(draft.ig_media_id)
    fb_ok = (not needed_fb) or bool(draft.fb_post_id)

    if ig_ok and fb_ok:
        draft.status = "published"
        draft.error = ""
        published_store.upsert(
            PublishedRecord(
                fingerprint=draft.fingerprint,
                content_type=draft.content_type,
                platforms=draft.platforms,
                caption=draft.caption,
                ig_media_id=draft.ig_media_id,
                fb_post_id=None,
                status="published",
                media_hash=draft.media_hash,
            )
        )
    else:
        draft.status = "failed"
        draft.error = redact_text("; ".join(errors)) if errors else "Partial publish failed."
        if draft.ig_media_id or draft.fb_post_id:
            published_store.upsert(
                PublishedRecord(
                    fingerprint=draft.fingerprint,
                    content_type=draft.content_type,
                    platforms=draft.platforms,
                    caption=draft.caption,
                    ig_media_id=draft.ig_media_id,
                    fb_post_id=draft.fb_post_id,
                    status="partial",
                    media_hash=draft.media_hash,
                )
            )
    return draft_store.save(draft)
