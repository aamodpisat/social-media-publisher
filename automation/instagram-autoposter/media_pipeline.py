"""Feed photos, image/video Stories and video Reels; one candidate per invocation."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

from PIL import Image
import main as core
import music

VIDEO_LIMIT = 250 * 1024 * 1024


def source_map(cfg):
    return getattr(cfg, "sources", {cfg.folder: "POST"})


def classify(cfg, parents, mime, filename):
    routes = {kind for folder, kind in source_map(cfg).items() if folder in parents}
    if len(routes) != 1:
        raise core.SafeError("File must belong to exactly one configured media folder.")
    kind = routes.pop()
    suffix = Path(filename).suffix.lower()
    image = mime in {"image/jpeg", "image/png"} and suffix in {".jpg", ".jpeg", ".png"}
    video = mime in {"video/mp4", "video/quicktime"} and suffix in {".mp4", ".mov"}
    if not ((kind == "POST" and image) or (kind == "STORY" and (image or video)) or (kind == "REEL" and video)):
        raise core.SafeError("Posts accept JPEG/PNG; Stories accept JPEG/PNG/MP4/MOV; Reels accept MP4/MOV.")
    return kind, video


def probe_video(path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True, check=True, timeout=60,
        )
        info = json.loads(result.stdout)
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        duration = float(info["format"]["duration"])
        if "mov" not in info["format"].get("format_name", "").split(","):
            raise ValueError()
        if not 0 < duration <= 900 or int(video["width"]) * int(video["height"]) > 40_000_000:
            raise ValueError()
        return duration
    except Exception:
        raise core.SafeError("Cannot inspect this MP4/MOV. Check FFmpeg/FFprobe installation, file validity, dimensions and duration (maximum 15 minutes).") from None


def prepare_media(record, raw):
    kind = record.get("kind", "POST")
    video = record.get("is_video", False)
    if not video:
        jpeg = core.prepare_jpeg(raw, story=kind == "STORY")
        return jpeg, "image/jpeg", jpeg
    work = core.ROOT / "work"
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="video-", dir=work) as directory:
        base = Path(directory)
        source = base / "source.mp4"
        target = base / "normalized.mp4"
        source.write_bytes(raw)
        duration = probe_video(source)
        if kind == "STORY" and duration > 60:
            raise core.SafeError("A video Story must be 60 seconds or shorter. Split it into separate files before uploading.")
        if kind == "REEL" and duration < 3:
            raise core.SafeError("A Reel must be at least 3 seconds long.")
        command = [
            "ffmpeg", "-v", "error", "-nostdin", "-y", "-protocol_whitelist", "file,pipe",
            "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:white,setsar=1,fps=30",
            "-c:v", "libx264", "-threads", "2", "-filter_threads", "1", "-preset", "fast", "-crf", "23",
            "-maxrate", "8M", "-bufsize", "16M", "-pix_fmt", "yuv420p", "-profile:v", "high", "-level:v", "4.1",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(target),
        ]
        try:
            subprocess.run(command, capture_output=True, check=True, timeout=1200)
            if target.stat().st_size > VIDEO_LIMIT:
                raise core.SafeError("Converted video exceeds this workflow's 250 MB limit. Compress it before upload.")
            media = target.read_bytes()
            montage = Image.new("RGB", (1080, 1920), "white")
            for index, fraction in enumerate((0.1, 0.35, 0.6, 0.85)):
                frame_path = base / f"frame-{index}.jpg"
                subprocess.run([
                    "ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", str(duration * fraction), "-i", str(target),
                    "-frames:v", "1", "-threads", "1", "-vf", "scale=540:960", str(frame_path),
                ], capture_output=True, check=True, timeout=60)
                with Image.open(frame_path) as frame:
                    montage.paste(frame, ((index % 2) * 540, (index // 2) * 960))
            output = io.BytesIO()
            montage.save(output, "JPEG", quality=85)
            return media, "video/mp4", output.getvalue()
        except core.SafeError:
            raise
        except Exception:
            raise core.SafeError("Video conversion/frame extraction failed. Verify FFmpeg with libx264/AAC support and enough disk space. Nothing was published.") from None


def publish_record(cfg, services, state, record):
    deadline = time.monotonic() + 600
    while True:
        status = services.graph("GET", record["container_id"], params={"fields": "status_code"}).get("status_code")
        if status == "PUBLISHED":
            core.finish_publish(cfg, state, record)
            return
        if record["publish_attempted"]:
            raise core.SafeError("Publishing was already attempted; its result is uncertain. No second publish request will be sent. Check Instagram and follow recovery.")
        if status == "FINISHED":
            break
        if status in {"ERROR", "EXPIRED"}:
            raise core.SafeError("Instagram rejected or expired this container. Item held for review; do not reset its record.")
        if status != "IN_PROGRESS":
            raise core.SafeError("Unknown media-container status. Item held for review.")
        if time.monotonic() >= deadline:
            raise core.SafeError("Media is still processing after ten minutes. The saved container will be checked on the next run.")
        time.sleep(5)
    record["publish_attempted"] = True
    record["publish_attempted_at"] = core.now()
    core.atomic_save(cfg.state_path, state)
    core.LOG.info("Publishing %s to Instagram...", record.get("publish_kind", record.get("kind", "POST")))
    result = services.graph("POST", f"{cfg.account}/media_publish", data={"creation_id": record["container_id"]})
    if not result.get("id"):
        raise core.SafeError("Publishing returned no media ID. Outcome held for review; no automatic second publishing request.")
    core.finish_publish(cfg, state, record, result["id"])


def container_fields(record, url):
    kind = record.get("publish_kind", record.get("kind", "POST"))
    key = "video_url" if record.get("output_is_video", record.get("is_video", False)) else "image_url"
    fields = {key: url}
    if kind == "STORY":
        fields["media_type"] = "STORIES"
        # Stories do not accept feed-style captions or hashtags.
    else:
        fields["caption"] = record["caption"]
        if kind == "REEL":
            fields["media_type"] = "REELS"
            fields["share_to_feed"] = "true"
    return fields


def run_once(cfg, services, state, dry_run=False):
    records = state["records"]
    if not dry_run:
        for record in records.values():
            if record["status"] != "pending" and record.get("object_name"):
                services.cleanup(record)
                core.atomic_save(cfg.state_path, state)
    pending = next(((fid, r) for fid, r in records.items() if r["status"] == "pending"), None)
    if pending:
        file_id, record = pending
        if dry_run:
            raise core.SafeError("Resolve the existing pending attempt before previewing another item.")
        services.validate_account(record.get("kind", "POST"))
        if record.get("container_id"):
            publish_record(cfg, services, state, record)
            services.cleanup(record)
            core.atomic_save(cfg.state_path, state)
            return
        raw = services.download({"id": file_id, "name": record["name"]})
        if core.hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise core.SafeError("Pending source bytes changed. Item held for review.")
    else:
        candidate = next(iter(services.files()), None)
        if not candidate:
            core.LOG.info("No new media found. Finished successfully.")
            return
        file_id = candidate["id"]
        if file_id in records:
            core.LOG.info("This Drive file is already tracked. No post created.")
            return
        raw = services.download(candidate)
        digest = core.hashlib.sha256(raw).hexdigest()
        if digest in {r["sha256"] for r in records.values()}:
            if not dry_run:
                records[file_id] = {"status": "duplicate", "sha256": digest, "name": candidate["name"], "tracked_at": core.now()}
                core.atomic_save(cfg.state_path, state)
            core.LOG.info("Identical media bytes already tracked. No post created.")
            return
        record = {"status": "pending", "sha256": digest, "name": candidate["name"],
                  "kind": candidate.get("kind", "POST"), "is_video": candidate.get("is_video", False),
                  "started_at": core.now(), "publish_attempted": False}
        if candidate.get("music"):
            record["music"] = music.permanent_selection(candidate["music"])
            record["output_is_video"] = True
            record["publish_kind"] = "REEL" if record["kind"] == "POST" else record["kind"]
        services.validate_account(record["kind"])
    core.LOG.info("Preparing %s (%s)...", record.get("kind", "POST"), "video" if record.get("is_video") else "image")
    media, mime, vision = services.prepare(record, raw)
    if not dry_run:
        records[file_id] = record
        core.atomic_save(cfg.state_path, state)
    if record.get("kind", "POST") == "STORY":
        record["caption"] = ""
    elif not record.get("caption"):
        context = record["name"]
        if record.get("is_video"):
            context += " [Video: supplied image is a 2x2 montage sampled at 10%, 35%, 60%, 85%; no audio/transcript is provided. Do not infer unseen events or speech.]"
        record["caption"] = services.caption(vision, context)
    if dry_run:
        folder = core.ROOT / "preview"
        folder.mkdir(exist_ok=True)
        target = folder / ("media.mp4" if mime == "video/mp4" else "media.jpg")
        target.write_bytes(media)
        (folder / "vision.jpg").write_bytes(vision)
        (folder / "caption.txt").write_text(record["caption"] + "\n", encoding="utf-8")
        core.LOG.info("Dry run complete: preview/media.*, vision.jpg and caption.txt. Story captions are intentionally empty. Nothing hosted or published.")
        return
    if not record.get("object_name"):
        suffix = ".mp4" if mime == "video/mp4" else ".jpg"
        record["object_name"] = f"instagram-temp/{uuid.uuid4().hex}{suffix}"
    core.atomic_save(cfg.state_path, state)
    url = services.upload_media(record["object_name"], media, mime)
    result = services.graph("POST", f"{cfg.account}/media", data=container_fields(record, url))
    if not result.get("id"):
        raise core.SafeError("Container creation returned no ID. Nothing was published.")
    record["container_id"] = result["id"]
    core.atomic_save(cfg.state_path, state)
    publish_record(cfg, services, state, record)
    services.cleanup(record)
    core.atomic_save(cfg.state_path, state)
