from __future__ import annotations

import os
from pathlib import Path

import pytest

from smp.config import reset_settings_cache


@pytest.fixture
def tmp_app(tmp_path, monkeypatch):
    data = tmp_path / "data"
    templates = tmp_path / "templates"
    data.mkdir()
    for kind in ("story", "posts", "reels"):
        (templates / kind / "assets").mkdir(parents=True)
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("TEMPLATES_DIR", str(templates))
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("POSTING_DAYS", "tue,wed,thu")
    monkeypatch.setenv("POSTING_TIMEZONE", "Asia/Kolkata")
    monkeypatch.delenv("META_PAGE_ACCESS_TOKEN", raising=False)
    reset_settings_cache()
    yield tmp_path
    reset_settings_cache()
