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
from test_workflow import FakeServices, png


class MediaServices(FakeServices):
    def __init__(self, kind="POST", video=False, publish_error=False):
        super().__init__([{"id": "one", "name": "media.mp4" if video else "image.png", "kind": kind, "is_video": video}], publish_error=publish_error)
        self.fields = []
        self.validation = []

    def validate_account(self, kind):
        self.validation.append(kind)

    def prepare(self, record, raw):
        return raw, "video/mp4" if record.get("is_video") else "image/jpeg", png()

    def upload_media(self, name, raw, mime):
        return "https://example.invalid/media"

    def graph(self, method, endpoint, **kwargs):
        if method == "POST" and endpoint.endswith("/media"):
            self.fields.append(kwargs["data"])
        return super().graph(method, endpoint, **kwargs)


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = SimpleNamespace(folder="root", sources={"posts": "POST", "stories": "STORY", "reels": "REEL"}, account="123", state_path=self.root / "state.json", binding={"folder_id": "root", "instagram_account_id": "123"})
        self.state = {"schema": 1, "binding": self.cfg.binding, "records": {}}
        core.atomic_save(self.cfg.state_path, self.state)

    def test_photo_feed_route(self):
        self.assertEqual(media.classify(self.cfg, ["posts"], "image/png", "one.png"), ("POST", False))

    def test_story_image_and_video_routes(self):
        self.assertEqual(media.classify(self.cfg, ["stories"], "image/jpeg", "one.jpg"), ("STORY", False))
        self.assertEqual(media.classify(self.cfg, ["stories"], "video/quicktime", "one.mov"), ("STORY", True))

    def test_reels_reject_images_and_posts_reject_videos(self):
        for parent, mime, name in [("reels", "image/jpeg", "one.jpg"), ("posts", "video/mp4", "one.mp4")]:
            with self.assertRaises(core.SafeError):
                media.classify(self.cfg, [parent], mime, name)

    def test_unknown_or_ambiguous_parent_rejected(self):
        for parents in [["outside"], ["stories", "posts"]]:
            with self.assertRaises(core.SafeError):
                media.classify(self.cfg, parents, "image/png", "one.png")

    def test_photo_post_has_caption(self):
        services = MediaServices()
        media.run_once(self.cfg, services, self.state)
        self.assertIn("image_url", services.fields[0])
        self.assertIn("caption", services.fields[0])
        self.assertNotIn("media_type", services.fields[0])

    def test_image_story_has_no_caption_or_ai_call(self):
        services = MediaServices("STORY")
        media.run_once(self.cfg, services, self.state)
        self.assertEqual(services.caption_count, 0)
        self.assertEqual(services.fields[0]["media_type"], "STORIES")
        self.assertIn("image_url", services.fields[0])
        self.assertNotIn("caption", services.fields[0])

    def test_video_story_uses_video_url(self):
        services = MediaServices("STORY", video=True)
        media.run_once(self.cfg, services, self.state)
        self.assertIn("video_url", services.fields[0])
        self.assertNotIn("caption", services.fields[0])

    def test_story_mentions_are_sent_for_images_and_videos(self):
        for video in (False, True):
            fields = media.container_fields({"kind": "STORY", "is_video": video,
                "story_mentions": ["aamod.pisat", "akanksha_pednekar_pisat"]}, "https://example.invalid/media")
            self.assertEqual(json.loads(fields["user_tags"]), [
                {"username": "aamod.pisat"}, {"username": "akanksha_pednekar_pisat"}])
            self.assertNotIn("caption", fields)

    def test_mentions_are_saved_only_for_new_story_records(self):
        self.cfg.story_mentions = ["aamod.pisat", "akanksha_pednekar_pisat"]
        service = MediaServices("STORY")
        media.run_once(self.cfg, service, self.state)
        self.assertEqual(self.state["records"]["one"]["story_mentions"], self.cfg.story_mentions)

    def test_story_mentions_do_not_leak_into_reels(self):
        fields = media.container_fields({"kind": "POST", "publish_kind": "REEL", "output_is_video": True,
            "caption": "caption", "story_mentions": ["aamod.pisat"]}, "https://example.invalid/media")
        self.assertNotIn("user_tags", fields)

    def test_reel_has_caption_and_reels_type(self):
        services = MediaServices("REEL", video=True)
        media.run_once(self.cfg, services, self.state)
        self.assertEqual(services.fields[0]["media_type"], "REELS")
        self.assertIn("video_url", services.fields[0])
        self.assertIn("caption", services.fields[0])
        self.assertEqual(services.caption_count, 1)

    def test_lost_response_never_republishes_reel(self):
        services = MediaServices("REEL", video=True, publish_error=True)
        with self.assertRaises(core.SafeError):
            media.run_once(self.cfg, services, self.state)
        retry = MediaServices("REEL", video=True)
        with self.assertRaises(core.SafeError):
            media.run_once(self.cfg, retry, core.load_state(self.cfg))
        self.assertEqual(retry.posts, [])

    def test_deduplication_applies_across_folders(self):
        self.state["records"]["old"] = {"status": "published", "sha256": hashlib.sha256(png()).hexdigest()}
        services = MediaServices("STORY")
        media.run_once(self.cfg, services, self.state)
        self.assertEqual(services.posts, [])
        self.assertEqual(self.state["records"]["one"]["status"], "duplicate")

    def test_saved_published_container_reconciles(self):
        self.state["records"]["old"] = {"status": "pending", "kind": "REEL", "sha256": hashlib.sha256(png()).hexdigest(), "container_id": "saved", "publish_attempted": True}
        services = MediaServices()
        services.statuses = iter(["PUBLISHED"])
        media.run_once(self.cfg, services, self.state)
        self.assertEqual(services.posts, [])
        self.assertEqual(self.state["records"]["old"]["status"], "published")

    def test_identity_uses_supported_facebook_login_fields(self):
        service = object.__new__(mcp.MCPServices)
        service.cfg = SimpleNamespace(account="123", expected_username="actual")
        def graph(method, endpoint, **kwargs):
            self.assertEqual((method, endpoint), ("GET", "123"))
            self.assertEqual(kwargs, {"params": {"fields": "id,username"}})
            return {"id": "123", "username": "actual"}
        service.graph = graph
        for kind in ("POST", "STORY", "REEL"):
            service.validate_account(kind)

    def test_wrong_account_id_is_blocked(self):
        service = object.__new__(mcp.MCPServices)
        service.cfg = SimpleNamespace(account="123", expected_username="actual")
        service.graph = lambda *args, **kwargs: {"id": "456", "username": "actual"}
        with self.assertRaises(core.SafeError):
            service.validate_account("STORY")

    def test_wrong_username_is_blocked(self):
        service = object.__new__(mcp.MCPServices)
        service.cfg = SimpleNamespace(account="123", expected_username="expected")
        service.graph = lambda *args, **kwargs: {"id": "123", "username": "other", "account_type": "BUSINESS"}
        with self.assertRaises(core.SafeError):
            service.validate_account("POST")

    def test_story_photo_is_full_portrait(self):
        output, mime, vision = media.prepare_media({"kind": "STORY", "is_video": False}, png())
        self.assertEqual(Image.open(io.BytesIO(output)).size, (1080, 1920))
        self.assertEqual(mime, "image/jpeg")

    def test_portrait_story_has_no_feed_padding(self):
        original = Image.new("RGB", (1080, 1920), (180, 30, 50))
        raw = io.BytesIO()
        original.save(raw, "PNG")
        output, _, _ = media.prepare_media({"kind": "STORY", "is_video": False}, raw.getvalue())
        with Image.open(io.BytesIO(output)) as result:
            self.assertEqual(result.size, (1080, 1920))
            for point in ((0, 0), (1079, 0), (0, 1919), (1079, 1919), (540, 960)):
                self.assertLess(max(abs(a-b) for a, b in zip(result.getpixel(point), (180, 30, 50))), 5)

    def test_nonportrait_story_keeps_entire_image(self):
        original = Image.new("RGB", (1080, 1080), (180, 30, 50))
        raw = io.BytesIO()
        original.save(raw, "PNG")
        output, _, _ = media.prepare_media({"kind": "STORY", "is_video": False}, raw.getvalue())
        with Image.open(io.BytesIO(output)) as result:
            self.assertEqual(result.getpixel((540, 0)), (255, 255, 255))
            self.assertLess(result.getpixel((0, 960))[1], 40)

    def test_real_video_transcode_and_sample_frames(self):
        source = self.root / "source.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x96:r=30", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "3", "-c:v", "libx264", "-threads", "1", "-c:a", "aac", str(source)], capture_output=True, check=True, timeout=60)
        output, mime, montage = media.prepare_media({"kind": "REEL", "is_video": True}, source.read_bytes())
        self.assertEqual(mime, "video/mp4")
        self.assertEqual(output[4:8], b"ftyp")
        self.assertEqual(Image.open(io.BytesIO(montage)).size, (1080, 1920))
        result = self.root / "result.mp4"
        result.write_bytes(output)
        self.assertGreaterEqual(media.probe_video(result), 3)

    def test_story_duration_over_sixty_seconds_is_not_trimmed(self):
        with patch.object(media, "probe_video", return_value=61):
            with self.assertRaisesRegex(core.SafeError, "60 seconds"):
                media.prepare_media({"kind": "STORY", "is_video": True}, b"fake")

    def test_reel_too_short_is_rejected(self):
        with patch.object(media, "probe_video", return_value=2):
            with self.assertRaisesRegex(core.SafeError, "at least 3"):
                media.prepare_media({"kind": "REEL", "is_video": True}, b"fake")


if __name__ == "__main__":
    unittest.main()
