from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, Sequence

CONTENT_TYPES = ("story", "posts", "reels")


def normalize_caption(caption: str) -> str:
    return " ".join(caption.strip().lower().split())


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(
    content_type: str,
    platforms: Sequence[str],
    caption: str,
    media_paths: Iterable[Path],
) -> str:
    h = hashlib.sha256()
    h.update(content_type.encode())
    h.update(b"|")
    h.update(",".join(sorted(platforms)).encode())
    h.update(b"|")
    h.update(normalize_caption(caption).encode())
    for path in media_paths:
        h.update(b"|")
        if path.is_file():
            h.update(file_sha256(path).encode())
        else:
            h.update(str(path).encode())
    return h.hexdigest()
