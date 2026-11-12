from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import httpx

from smp.config import get_settings
from smp.redact import redact, redact_text


class ContentstackError(RuntimeError):
    pass


def upload_asset(path: Path) -> str:
    """Upload one media file through classic CMA and return its public CDN URL."""
    settings = get_settings()
    if not settings.contentstack_ready():
        raise ContentstackError("Set CONTENTSTACK_API_KEY and CONTENTSTACK_MANAGEMENT_TOKEN in .env.")
    suffix = path.suffix.lower()
    host = settings.contentstack_image_host if suffix in {".jpg", ".jpeg", ".png", ".webp"} else settings.contentstack_video_host
    try:
        with path.open("rb") as media, httpx.Client(timeout=180.0) as client:
            response = client.post(
                f"{settings.contentstack_api_host.rstrip('/')}/v3/assets",
                headers={
                    "api_key": settings.contentstack_api_key,
                    "authorization": settings.contentstack_management_token,
                },
                data={"asset[title]": path.stem, "asset[description]": "Instagram portfolio media"},
                files={"asset[upload]": (path.name, media, _mime(path))},
            )
        result: Dict[str, Any] = response.json()
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise ContentstackError(redact_text(str(exc))) from None
    if response.status_code >= 400 or result.get("error"):
        raise ContentstackError(redact(result.get("error") or result) or "Contentstack asset upload failed.")
    asset = result.get("asset") or {}
    url = asset.get("url")
    if not url:
        raise ContentstackError("Contentstack upload response did not include an asset URL.")
    # Keep the file-specific path and identifiers from CMA; only normalize its CDN host.
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(url)
    return urlunsplit(("https", host.removeprefix("https://").removeprefix("http://"), parts.path, parts.query, ""))


def _mime(path: Path) -> str:
    import mimetypes
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
