from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from smp.config import get_settings

FRONT_MATTER = "---"


def parse_template(path: Path) -> Tuple[Dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith(FRONT_MATTER):
        return {}, text.strip()
    rest = text[len(FRONT_MATTER) :].lstrip("\n")
    end = rest.find(f"\n{FRONT_MATTER}")
    if end == -1:
        raise ValueError(f"{path}: missing closing front matter ---")
    meta = yaml.safe_load(rest[:end]) or {}
    body = rest[end + len(FRONT_MATTER) + 1 :].strip()
    if not isinstance(meta, dict):
        raise ValueError(f"{path}: front matter must be a mapping")
    return meta, body


def iter_templates() -> List[Tuple[str, Path, Dict[str, Any], str]]:
    root = get_settings().templates_dir
    found: List[Tuple[str, Path, Dict[str, Any], str]] = []
    for content_type in ("story", "posts", "reels"):
        folder = root / content_type
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            if path.name.startswith("_"):
                continue
            meta, body = parse_template(path)
            found.append((content_type, path, meta, body))
    return found


def resolve_media(content_type: str, meta: Dict[str, Any], template_path: Path) -> List[Path]:
    raw = meta.get("media") or meta.get("assets") or []
    if isinstance(raw, str):
        raw = [raw]
    folder = get_settings().templates_dir / content_type
    paths: List[Path] = []
    for item in raw:
        candidate = Path(item)
        if not candidate.is_absolute():
            candidate = (folder / item).resolve()
        paths.append(candidate)
    return paths
