from smp.publisher.meta import instagram_container_payload
from smp.store.drafts import Draft


def _draft(content_type: str, media: str) -> Draft:
    return Draft(
        id="1",
        batch_id="2026-W37",
        content_type=content_type,
        platforms=["instagram"],
        caption="hi",
        media_paths=[media],
        fingerprint="abc",
        title="t",
    )


def test_story_payload_is_stories():
    p = instagram_container_payload(_draft("story", "x.jpg"), "https://cdn.example/x.jpg")
    assert p["media_type"] == "STORIES"
    assert p["media_type"] != "REELS"
    assert "image_url" in p


def test_reels_payload_is_reels():
    p = instagram_container_payload(_draft("reels", "x.mp4"), "https://cdn.example/x.mp4")
    assert p["media_type"] == "REELS"
    assert p["media_type"] != "STORIES"
    assert "video_url" in p


def test_post_image_is_not_story_or_reel():
    p = instagram_container_payload(_draft("posts", "x.jpg"), "https://cdn.example/x.jpg")
    assert p.get("media_type") not in {"STORIES", "REELS"}
    assert p["image_url"].startswith("https://")
