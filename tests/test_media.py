from pathlib import Path

from smp.publisher.media import MediaError, validate_media
import pytest


def test_reels_reject_image(tmp_path):
    img = tmp_path / "x.jpg"
    img.write_bytes(b"x")
    with pytest.raises(MediaError):
        validate_media("reels", [img])


def test_reels_accept_mp4(tmp_path):
    video = tmp_path / "x.mp4"
    video.write_bytes(b"x")
    validate_media("reels", [video])


def test_missing_file():
    with pytest.raises(MediaError):
        validate_media("posts", [Path("/no/such.jpg")])
