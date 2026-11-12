from smp.redact import redact, redact_text


def test_redact_bearer_and_graph_token():
    text = "Authorization: Bearer EAABsbd123abc access_token=EAABsecret"
    out = redact_text(text)
    assert "EAABsbd123abc" not in out
    assert "[REDACTED]" in out


def test_redact_openai_key():
    assert "sk-live-secret" not in redact_text("key sk-live-secret used")


def test_redact_mapping():
    out = redact({"access_token": "secret", "id": "1"})
    assert out["access_token"] == "[REDACTED]"
    assert out["id"] == "1"
