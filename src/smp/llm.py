from __future__ import annotations

import base64
import mimetypes
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from smp.config import get_settings
from smp.redact import redact, redact_text


class LlmError(RuntimeError):
    pass


def complete(system: str, user: str) -> str:
    return _complete(system, user)


def complete_with_media(system: str, user: str, path: Path) -> str:
    """Caption based on visible media; videos are represented by sampled frames."""
    frames = [path]
    if path.suffix.lower() in {".mp4", ".mov", ".m4v"}:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise LlmError("Video captioning needs ffmpeg installed so the model can inspect video frames.")
        with tempfile.TemporaryDirectory(prefix="smp-frames-") as tmp:
            pattern = str(Path(tmp) / "frame-%02d.jpg")
            proc = subprocess.run(
                [ffmpeg, "-v", "error", "-i", str(path), "-vf", "fps=1/5,scale=768:-1", "-frames:v", "6", pattern],
                capture_output=True, text=True, timeout=90,
            )
            if proc.returncode:
                raise LlmError("Could not extract preview frames from the video.")
            frames = sorted(Path(tmp).glob("frame-*.jpg"))
            if not frames:
                raise LlmError("No preview frames could be extracted from the video.")
            return _complete_with_images(system, user, frames)
    return _complete_with_images(system, user, frames)


def _complete_with_images(system: str, user: str, paths: list[Path]) -> str:
    settings = get_settings()
    if not settings.llm_ready():
        raise LlmError("LLM is not configured. Set LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL in .env.")
    parts: list[dict[str, Any]] = [{"type": "text", "text": user}]
    for path in paths:
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
    return _request_completion(system, parts)


def _complete(system: str, user: str) -> str:
    return _request_completion(system, user)


def _request_completion(system: str, user_content: Any) -> str:
    settings = get_settings()
    if not settings.llm_ready():
        raise LlmError("LLM is not configured. Set LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL in .env.")

    url = f"{settings.llm_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "temperature": 0.7,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    }
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=60.0)
        response.raise_for_status()
        data: Dict[str, Any] = response.json()
    except httpx.HTTPStatusError as exc:
        raise LlmError(redact_text(f"LLM HTTP {exc.response.status_code}: {exc.response.text}")) from None
    except httpx.HTTPError as exc:
        raise LlmError(redact_text(str(exc))) from None

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LlmError("LLM response missing choices[0].message.content") from None
    if not isinstance(content, str) or not content.strip():
        raise LlmError("LLM returned empty content.")
    return content.strip()
