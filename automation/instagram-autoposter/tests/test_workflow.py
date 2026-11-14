import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
import main as app


def png():
    data = io.BytesIO()
    Image.new("RGBA", (100, 400), (255, 0, 0, 100)).save(data, "PNG")
    return data.getvalue()


CAPTION = "A practical tip for your day\nTry this simple step.\nVisit the link in our bio.\n#Industry #Learning #Tips #DailyPractice #MyBrand"


class FakeServices:
    def __init__(self, files=None, statuses=None, publish_error=False):
        self.input_files = files or []
        self.statuses = iter(statuses or ["FINISHED"])
        self.publish_error = publish_error
        self.posts = []
        self.cleaned = []
        self.download_count = 0
        self.caption_count = 0

    def files(self):
        return iter(self.input_files)

    def download(self, file):
        self.download_count += 1
        return png()

    def caption(self, jpeg, filename):
        self.caption_count += 1
        return CAPTION

    def upload(self, object_name, jpeg):
        return "https://example.invalid/image.jpg"

    def graph(self, method, endpoint, **kwargs):
        if method == "GET":
            return {"status_code": next(self.statuses)}
        self.posts.append(endpoint)
        if endpoint.endswith("/media_publish"):
            if self.publish_error:
                raise app.SafeError("Simulated lost response")
            return {"id": "published-id"}
        return {"id": "container-id"}

    def cleanup(self, record):
        self.cleaned.append(record.pop("object_name", None))


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = SimpleNamespace(state_path=Path(self.tmp.name) / "state.json", account="123", binding={"folder_id": "folder", "instagram_account_id": "123"})
        self.state = {"schema": 1, "binding": self.cfg.binding, "records": {}}
        app.atomic_save(self.cfg.state_path, self.state)

    def test_empty_folder_success(self):
        services = FakeServices()
        app.run_once(self.cfg, services, self.state)
        self.assertEqual(services.posts, [])

    def test_only_one_image_published(self):
        services = FakeServices([{"id": "one", "name": "one.png"}, {"id": "two", "name": "two.png"}])
        app.run_once(self.cfg, services, self.state)
        self.assertEqual(services.posts, ["123/media", "123/media_publish"])
        self.assertEqual(services.download_count, 1)
        self.assertEqual(self.state["records"]["one"]["status"], "published")
        self.assertNotIn("two", self.state["records"])

    def test_duplicate_file_id_skipped(self):
        self.state["records"]["one"] = {"status": "published", "sha256": hashlib.sha256(png()).hexdigest()}
        services = FakeServices([{"id": "one", "name": "one.png"}])
        app.run_once(self.cfg, services, self.state)
        self.assertEqual(services.download_count, 0)
        self.assertEqual(services.posts, [])

    def test_same_bytes_under_new_name_skipped(self):
        self.state["records"]["one"] = {"status": "published", "sha256": hashlib.sha256(png()).hexdigest()}
        services = FakeServices([{"id": "two", "name": "renamed.png"}])
        app.run_once(self.cfg, services, self.state)
        self.assertEqual(self.state["records"]["two"]["status"], "duplicate")
        self.assertEqual(services.posts, [])

    def test_lost_publish_response_is_never_retried(self):
        services = FakeServices([{"id": "one", "name": "one.png"}], publish_error=True)
        with self.assertRaises(app.SafeError):
            app.run_once(self.cfg, services, self.state)
        restored = app.load_state(self.cfg)
        self.assertTrue(restored["records"]["one"]["publish_attempted"])
        second = FakeServices(statuses=["FINISHED"])
        with self.assertRaises(app.SafeError):
            app.run_once(self.cfg, second, restored)
        self.assertEqual(second.posts, [])

    def test_published_container_reconciles_after_crash(self):
        record = {"status": "pending", "sha256": hashlib.sha256(png()).hexdigest(), "container_id": "saved", "publish_attempted": True, "object_name": "temporary.jpg"}
        self.state["records"]["one"] = record
        services = FakeServices(statuses=["PUBLISHED"])
        app.run_once(self.cfg, services, self.state)
        self.assertEqual(record["status"], "published")
        self.assertEqual(services.posts, [])
        self.assertEqual(services.cleaned, ["temporary.jpg"])

    def test_saved_container_is_resumed_not_recreated(self):
        self.state["records"]["one"] = {"status": "pending", "sha256": hashlib.sha256(png()).hexdigest(), "container_id": "saved", "publish_attempted": False}
        services = FakeServices(statuses=["FINISHED"])
        app.run_once(self.cfg, services, self.state)
        self.assertEqual(services.posts, ["123/media_publish"])
        self.assertEqual(services.download_count, 0)

    def test_prepublication_crash_recovers_caption(self):
        self.state["records"]["one"] = {"status": "pending", "name": "one.png", "sha256": hashlib.sha256(png()).hexdigest(), "publish_attempted": False, "caption": CAPTION}
        app.atomic_save(self.cfg.state_path, self.state)
        services = FakeServices()
        app.run_once(self.cfg, services, self.state)
        self.assertEqual(services.caption_count, 0)
        self.assertEqual(services.posts, ["123/media", "123/media_publish"])

    def test_publish_intent_saved_before_network_call(self):
        self.state["records"]["one"] = {"status": "pending", "sha256": hashlib.sha256(png()).hexdigest(), "container_id": "saved", "publish_attempted": False}
        services = FakeServices()
        original = services.graph
        def graph(method, endpoint, **kwargs):
            if method == "POST":
                self.assertTrue(json.loads(self.cfg.state_path.read_text())["records"]["one"]["publish_attempted"])
            return original(method, endpoint, **kwargs)
        services.graph = graph
        app.run_once(self.cfg, services, self.state)

    def test_missing_corrupt_wrong_account_fail_closed(self):
        self.cfg.state_path.unlink()
        with self.assertRaises(app.SafeError):
            app.load_state(self.cfg)
        self.cfg.state_path.write_text("not json")
        with self.assertRaises(app.SafeError):
            app.load_state(self.cfg)
        self.state["binding"] = {"different": "account"}
        app.atomic_save(self.cfg.state_path, self.state)
        with self.assertRaises(app.SafeError):
            app.load_state(self.cfg)

    def test_cleanup_failure_preserves_published_status(self):
        services = FakeServices([{"id": "one", "name": "one.png"}])
        services.cleanup = lambda record: (_ for _ in ()).throw(app.SafeError("cleanup unavailable"))
        with self.assertRaises(app.SafeError):
            app.run_once(self.cfg, services, self.state)
        self.assertEqual(app.load_state(self.cfg)["records"]["one"]["status"], "published")

    def test_http_never_retries_post(self):
        session = unittest.mock.Mock()
        session.request.side_effect = app.requests.Timeout()
        with self.assertRaises(app.SafeError):
            app.http(session, "POST", "https://example.invalid/publish")
        self.assertEqual(session.request.call_count, 1)

    def test_valid_and_invalid_captions(self):
        self.assertEqual(app.caption_problems(CAPTION, "#MyBrand"), [])
        self.assertTrue(app.caption_problems("x" * 125 + "\n#Tag", "#MyBrand"))

    def test_png_transparency_and_ratio_convert(self):
        jpeg = app.prepare_jpeg(png())
        image = Image.open(io.BytesIO(jpeg))
        self.assertEqual(image.format, "JPEG")
        self.assertGreaterEqual(image.width / image.height, 0.8)
        self.assertLessEqual(image.width / image.height, 1.91)
        self.assertEqual(image.mode, "RGB")

    def test_invalid_image_is_rejected(self):
        with self.assertRaises(app.SafeError):
            app.prepare_jpeg(b"not an image")


if __name__ == "__main__":
    unittest.main()
