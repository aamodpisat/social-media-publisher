import hashlib
import io
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
import main as core
import mcp_main as mcp
import media_pipeline as media
import music
from test_media import MediaServices
from test_workflow import png


class MusicTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = self.root / "track.mp3"
        self.audio.write_bytes(b"test bytes")
        self.selection = {
            "file_id": "track", "filename": "romantic.mp3", "mime_type": "audio/mpeg",
            "parent_ids": ["music"], "file_size_bytes": self.audio.stat().st_size,
            "sha256": hashlib.sha256(self.audio.read_bytes()).hexdigest(),
            "local_path": str(self.audio), "mood": "romantic",
        }

    def test_music_rejects_wrong_parent_size_and_changed_bytes(self):
        for update in ({"parent_ids": ["outside"]}, {"file_size_bytes": 100}, {"sha256": "0" * 64}):
            with self.assertRaises(core.SafeError):
                music.read_handoff(dict(self.selection, **update), "music")
        self.assertEqual(music.read_handoff(self.selection, "music"), self.selection)

    def test_music_selection_is_saved_without_machine_path(self):
        cfg = SimpleNamespace(state_path=self.root / "state.json", account="123")
        for kind, published_kind in (("STORY", "STORIES"), ("POST", "REELS")):
            state = {"records": {}}
            service = MediaServices(kind)
            service.input_files[0]["music"] = self.selection
            media.run_once(cfg, service, state)
            record = state["records"]["one"]
            self.assertNotIn("local_path", record["music"])
            self.assertEqual(record["kind"], kind)
            self.assertEqual(service.fields[0]["media_type"], published_kind)
            self.assertIn("video_url", service.fields[0])
            self.assertEqual(record["status"], "published")

    def test_real_photo_music_render_has_full_size_audio_and_duration(self):
        subprocess.run([
            "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=1", "-c:a", "libmp3lame", str(self.audio)
        ], check=True, capture_output=True, timeout=30)
        selection = dict(self.selection, file_size_bytes=self.audio.stat().st_size,
                         sha256=hashlib.sha256(self.audio.read_bytes()).hexdigest())
        jpeg = core.prepare_jpeg(png(), story=True)
        with patch.object(core, "ROOT", self.root):
            output = music.render_photo(jpeg, selection)
        target = self.root / "result.mp4"
        target.write_bytes(output)
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(target)
        ], check=True, capture_output=True, timeout=30)
        result = json.loads(probe.stdout)
        video = next(s for s in result["streams"] if s["codec_type"] == "video")
        audio = next(s for s in result["streams"] if s["codec_type"] == "audio")
        self.assertEqual((video["width"], video["height"]), (1080, 1920))
        self.assertEqual(audio["codec_name"], "aac")
        self.assertAlmostEqual(float(result["format"]["duration"]), 15, delta=0.2)

    def test_pending_music_cannot_be_replaced(self):
        raw = png()
        photo = self.root / "photo.png"
        photo.write_bytes(raw)
        handoff = {"file_id": "one", "filename": "photo.png", "mime_type": "image/png",
                   "parent_ids": ["stories"], "file_size_bytes": len(raw),
                   "sha256": hashlib.sha256(raw).hexdigest(), "local_path": str(photo),
                   "music": self.selection}
        path = self.root / "handoff.json"
        path.write_text(json.dumps(handoff))
        cfg = SimpleNamespace(folder="root", sources={"stories": "STORY"}, music_folder="music")
        state = {"records": {"one": {"status": "pending", "kind": "STORY", "name": "photo.png",
                  "music": dict(music.permanent_selection(self.selection), file_id="another")}}}
        with self.assertRaisesRegex(core.SafeError, "Pending music selection"):
            mcp.read_input(path, cfg, state)

    def test_invalid_audio_does_not_render(self):
        with patch.object(core, "ROOT", self.root), self.assertRaises(core.SafeError):
            music.render_photo(core.prepare_jpeg(png(), story=True), self.selection)

    def test_music_does_not_bypass_photo_duplicate_protection(self):
        cfg = SimpleNamespace(state_path=self.root / "state.json", account="123")
        state = {"records": {"old": {"status": "published", "sha256": hashlib.sha256(png()).hexdigest()}}}
        service = MediaServices("STORY")
        service.input_files[0]["music"] = self.selection
        media.run_once(cfg, service, state)
        self.assertEqual(service.posts, [])
        self.assertEqual(state["records"]["one"]["status"], "duplicate")

    def test_music_failure_does_not_create_publishing_intent(self):
        cfg = SimpleNamespace(state_path=self.root / "state.json", account="123")
        state = {"records": {}}
        service = MediaServices("STORY")
        service.input_files[0]["music"] = self.selection
        with patch.object(service, "prepare", side_effect=core.SafeError("bad audio")):
            with self.assertRaises(core.SafeError):
                media.run_once(cfg, service, state)
        self.assertEqual(service.posts, [])
        self.assertEqual(state["records"], {})
