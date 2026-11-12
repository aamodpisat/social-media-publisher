from __future__ import annotations

from pathlib import Path
from typing import List

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v"}

STORY_OK = IMAGE_EXT | VIDEO_EXT
POST_OK = IMAGE_EXT | VIDEO_EXT
REEL_OK = VIDEO_EXT


class MediaError(ValueError):
    pass


def validate_media(content_type: str, paths: List[Path]) -> None:
    if not paths:
        raise MediaError(f"{content_type}: at least one media file is required.")
    for path in paths:
        if not path.is_file():
            raise MediaError(f"Media not found: {path}")
        ext = path.suffix.lower()
        if content_type == "reels" and ext not in REEL_OK:
            raise MediaError("reels require a video file (.mp4, .mov, .m4v).")
        if content_type == "story" and ext not in STORY_OK:
            raise MediaError("story media must be an image or video.")
        if content_type == "posts" and ext not in POST_OK:
            raise MediaError("posts media must be an image or video.")
