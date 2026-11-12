from pathlib import Path

from smp.content.fingerprint import fingerprint, normalize_caption


def test_same_caption_and_file_match(tmp_path):
    media = tmp_path / "a.jpg"
    media.write_bytes(b"abc")
    a = fingerprint("posts", ["instagram"], "Hello  World", [media])
    b = fingerprint("posts", ["instagram"], "hello world", [media])
    assert a == b


def test_caption_tweak_changes_hash(tmp_path):
    media = tmp_path / "a.jpg"
    media.write_bytes(b"abc")
    a = fingerprint("posts", ["instagram"], "hello", [media])
    b = fingerprint("posts", ["instagram"], "hello!", [media])
    assert a != b


def test_type_change_allowed(tmp_path):
    media = tmp_path / "a.jpg"
    media.write_bytes(b"abc")
    a = fingerprint("posts", ["instagram"], "hello", [media])
    b = fingerprint("story", ["instagram"], "hello", [media])
    assert a != b


def test_normalize():
    assert normalize_caption("  A  B ") == "a b"
