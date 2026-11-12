import httpx
import pytest

from smp import llm


def test_llm_url_and_auth(tmp_app, monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Hello from the model"}}]},
            request=request,
        )

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    text = llm.complete("sys", "user brief only")
    assert text == "Hello from the model"
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["headers"]["Authorization"].startswith("Bearer ")
    assert "test-key" not in str(captured["json"])
    assert captured["json"]["model"] == "test-model"
