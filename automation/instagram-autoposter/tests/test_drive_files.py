import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import main as core
import drive_files


class FakeResponse:
    def __init__(self, status, payload=None, content=b"", redirect=False):
        self.status_code = status
        self._payload = payload or {}
        self._content = content
        self.is_redirect = redirect
        self.headers = {}

    def json(self):
        return self._payload

    def iter_content(self, chunk_size):
        if self._content:
            yield self._content


class FakeSession:
    def __init__(self, metadata, content=b"", delete_status=204, download_status=200):
        self.metadata = metadata
        self.content = content
        self.delete_status = delete_status
        self.download_status = download_status
        self.calls = []

    def get(self, url, params=None, timeout=None, stream=None, allow_redirects=None):
        self.calls.append(("GET", url, params, allow_redirects))
        if params and params.get("alt") == "media":
            return FakeResponse(self.download_status, content=self.content)
        if self.metadata is None:
            return FakeResponse(404)
        return FakeResponse(200, self.metadata)

    def delete(self, url, params=None, timeout=None, allow_redirects=None):
        self.calls.append(("DELETE", url, params, allow_redirects))
        return FakeResponse(self.delete_status)


def photo(file_id="photo1", parent="posts", size=4):
    return {
        "id": file_id,
        "name": "wedding.jpg",
        "mimeType": "image/jpeg",
        "parents": [parent],
        "size": str(size),
        "trashed": False,
    }


class DriveFileTests(unittest.TestCase):
    def test_download_writes_original_and_sha256_without_inventing_md5(self):
        raw = b"jpeg-bytes"
        metadata = photo(size=len(raw))
        session = FakeSession(metadata, raw)
        with TemporaryDirectory() as directory:
            manifest = drive_files.download_original(session, "photo1", directory, {"posts"}, "music")
            path = Path(manifest["local_path"])
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(manifest["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(manifest["file_size_bytes"], len(raw))
            self.assertNotIn("md5_checksum", manifest)
            self.assertTrue(path.name.startswith("photo1"))

    def test_download_keeps_provider_md5_when_present(self):
        raw = b"jpeg-bytes"
        metadata = photo(size=len(raw))
        metadata["md5Checksum"] = "ab" * 16
        session = FakeSession(metadata, raw)
        with TemporaryDirectory() as directory:
            manifest = drive_files.download_original(session, "photo1", directory, {"posts"}, "music")
        self.assertEqual(manifest["md5_checksum"], "ab" * 16)

    def test_download_refuses_oversize_before_saving(self):
        metadata = photo(size=drive_files.IMAGE_LIMIT + 1)
        session = FakeSession(metadata, b"x")
        with TemporaryDirectory() as directory:
            with self.assertRaises(core.SafeError):
                drive_files.download_original(session, "photo1", directory, {"posts"}, "music")
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertTrue(all(call[0] == "GET" and (call[2] or {}).get("alt") != "media" for call in session.calls))

    def test_download_refuses_a_redirect(self):
        raw = b"jpeg-bytes"
        metadata = photo(size=len(raw))

        class RedirectSession(FakeSession):
            def get(self, url, params=None, timeout=None, stream=None, allow_redirects=None):
                if params and params.get("alt") == "media":
                    return FakeResponse(302, redirect=True)
                return super().get(url, params=params, timeout=timeout, stream=stream, allow_redirects=allow_redirects)

        with TemporaryDirectory() as directory:
            with self.assertRaises(core.SafeError):
                drive_files.download_original(RedirectSession(metadata, raw), "photo1", directory, {"posts"}, "music")

    def test_delete_published_source_calls_delete_once(self):
        raw = b"jpeg"
        metadata = photo(size=len(raw))
        session = FakeSession(metadata, raw)
        outcome = drive_files.delete_published_source(session, "photo1", "published", {"posts"}, "music")
        self.assertEqual(outcome, "deleted")
        self.assertEqual([call[0] for call in session.calls], ["GET", "DELETE"])

    def test_delete_refuses_music_and_does_not_call_delete(self):
        metadata = {
            "id": "song", "name": "romantic.mp3", "mimeType": "audio/mpeg",
            "parents": ["music"], "size": "4", "trashed": False,
        }
        session = FakeSession(metadata)
        with self.assertRaises(core.SafeError) as caught:
            drive_files.delete_published_source(session, "song", "published", {"posts"}, "music")
        self.assertIn("Music", str(caught.exception))
        self.assertNotIn("DELETE", [call[0] for call in session.calls])

    def test_delete_refuses_pending_failed_and_missing_records(self):
        metadata = photo()
        for status in ("pending", "duplicate", "retired", None):
            session = FakeSession(metadata)
            with self.assertRaises(core.SafeError):
                drive_files.delete_published_source(session, "photo1", status, {"posts"}, "music")
            self.assertNotIn("DELETE", [call[0] for call in session.calls])

    def test_delete_refuses_a_file_outside_the_publishing_folders(self):
        metadata = photo(parent="somewhere-else")
        session = FakeSession(metadata)
        with self.assertRaises(core.SafeError):
            drive_files.delete_published_source(session, "photo1", "published", {"posts"}, "music")
        self.assertNotIn("DELETE", [call[0] for call in session.calls])

    def test_delete_removes_a_published_file_that_is_still_in_trash(self):
        metadata = photo()
        metadata["trashed"] = True
        session = FakeSession(metadata)
        self.assertEqual(
            drive_files.delete_published_source(session, "photo1", "published", {"posts"}, "music"),
            "deleted")
        self.assertIn("DELETE", [call[0] for call in session.calls])

    def test_delete_of_missing_published_file_does_not_raise(self):
        session = FakeSession(None)
        self.assertEqual(
            drive_files.delete_published_source(session, "photo1", "published", {"posts"}, "music"),
            "already-absent")
        self.assertNotIn("DELETE", [call[0] for call in session.calls])

    def test_login_failure_does_not_reveal_the_refresh_token(self):
        secret = "refresh-token-must-not-leak"

        class BrokenCredentials:
            token = None

            def refresh(self, request):
                raise RuntimeError(secret)

        with patch.dict("os.environ", {
            "GOOGLE_OAUTH_CLIENT_ID": "client",
            "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
            "GOOGLE_DRIVE_REFRESH_TOKEN": secret,
        }):
            with self.assertRaises(core.SafeError) as caught:
                drive_files.authorized_session(BrokenCredentials())
        self.assertNotIn(secret, str(caught.exception))

    def test_cli_delete_uses_the_posting_record(self):
        raw = b"jpeg"
        metadata = photo(size=len(raw))
        session = FakeSession(metadata, raw)
        with TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            core.atomic_save(state_path, {
                "schema": 1,
                "binding": {"folder_id": "root", "instagram_account_id": "123"},
                "records": {"photo1": {"status": "published", "sha256": "a" * 64}},
            })
            cfg = type("Cfg", (), {
                "sources": {"posts": "POST", "stories": "STORY", "reels": "REEL"},
                "music_folder": "music",
                "state_path": state_path,
                "binding": {"folder_id": "root", "instagram_account_id": "123"},
            })()
            with patch.object(drive_files.mcp_main, "apply_host_aliases"), \
                    patch.object(drive_files.mcp_main, "MCPConfig", return_value=cfg), \
                    patch.object(drive_files, "authorized_session", return_value=session):
                code = drive_files.main(["--delete", "--file-id", "photo1"])
        self.assertEqual(code, 0)
        self.assertIn("DELETE", [call[0] for call in session.calls])


if __name__ == "__main__":
    unittest.main()
