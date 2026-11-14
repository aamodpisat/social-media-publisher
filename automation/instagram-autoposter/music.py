"""Verified local music handoff and still-photo video rendering. No Drive client."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

import main as core

MAX_AUDIO = 25 * 1024 * 1024


def read_handoff(value, folder):
    try:
        if not folder or value["parent_ids"] != [folder]:
            raise ValueError()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value["file_id"]):
            raise ValueError()
        if value["mime_type"] != "audio/mpeg" or Path(value["filename"]).suffix.lower() != ".mp3":
            raise ValueError()
        size = value["file_size_bytes"]
        if type(size) is not int or not 0 < size <= MAX_AUDIO:
            raise ValueError()
        path = Path(value["local_path"])
        if not path.is_absolute() or not path.is_file() or path.stat().st_size != size:
            raise ValueError()
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != value["sha256"]:
            raise ValueError()
        if value["mood"] not in {"romantic", "cinematic", "instrumental", "celebration"}:
            raise ValueError()
        return {key: value[key] for key in (
            "file_id", "filename", "mime_type", "parent_ids", "file_size_bytes", "sha256", "mood", "local_path")}
    except (KeyError, TypeError, ValueError, OSError):
        raise core.SafeError("Invalid music handoff. Supply a verified original MP3 (maximum 25 MB) from the configured music folder, with size and SHA-256.") from None


def permanent_selection(selection):
    return {key: value for key, value in selection.items() if key != "local_path"}


def render_photo(jpeg, selection):
    """Render 15 seconds, looping short audio, with fades and a static photo."""
    # Recheck bytes immediately before invoking FFmpeg; don't trust an old manifest.
    path = Path(selection["local_path"])
    raw = path.read_bytes()
    if len(raw) != selection["file_size_bytes"] or hashlib.sha256(raw).hexdigest() != selection["sha256"]:
        raise core.SafeError("Music bytes changed after verification. Refetch the original track.")
    work = core.ROOT / "work"
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="music-", dir=work) as directory:
        base = Path(directory)
        photo, audio, target = base / "photo.jpg", base / "audio.mp3", base / "story.mp4"
        photo.write_bytes(jpeg)
        audio.write_bytes(raw)
        try:
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams", "-of", "json", str(audio)
            ], capture_output=True, check=True, timeout=30)
            streams = json.loads(probe.stdout)["streams"]
            if not any(s.get("codec_type") == "audio" and s.get("codec_name") == "mp3" for s in streams):
                raise ValueError()
            subprocess.run([
                "ffmpeg", "-v", "error", "-nostdin", "-y", "-protocol_whitelist", "file,pipe",
                "-loop", "1", "-framerate", "30", "-i", str(photo),
                "-stream_loop", "-1", "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                "-t", "15", "-vf", "setsar=1,format=yuv420p",
                "-af", "afade=t=in:st=0:d=0.5,afade=t=out:st=13.5:d=1.5",
                "-c:v", "libx264", "-threads", "2", "-filter_threads", "1", "-preset", "fast",
                "-tune", "stillimage", "-crf", "23", "-c:a", "aac", "-b:a", "128k",
                "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(target)
            ], capture_output=True, check=True, timeout=300)
            if target.stat().st_size > 250 * 1024 * 1024:
                raise ValueError()
            return target.read_bytes()
        except Exception:
            raise core.SafeError("Music rendering failed. Check the original MP3 and FFmpeg; nothing was published.") from None
