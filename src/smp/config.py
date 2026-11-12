from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import FrozenSet, List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_POSTING_DAYS: FrozenSet[str] = frozenset({"sat", "sun"})

_SECRET_ENV_NAMES = frozenset(
    {
        "LLM_API_KEY",
        "META_PAGE_ACCESS_TOKEN",
        "CONTENTSTACK_MANAGEMENT_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    }
)


def _parse_days(raw: str) -> FrozenSet[str]:
    parts = [p.strip().lower()[:3] for p in raw.split(",") if p.strip()]
    invalid = [p for p in parts if p not in WEEKDAYS]
    if invalid:
        raise ValueError(f"Invalid POSTING_DAYS: {invalid}. Use mon,tue,wed,thu,fri,sat,sun.")
    return frozenset(parts) if parts else DEFAULT_POSTING_DAYS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")

    posting_days: str = Field(default="sat,sun", alias="POSTING_DAYS")
    posting_time: str = Field(default="11:00", alias="POSTING_TIME")
    posting_timezone: str = Field(default="Asia/Kolkata", alias="POSTING_TIMEZONE")

    meta_graph_version: str = Field(default="v21.0", alias="META_GRAPH_VERSION")
    meta_page_id: str = Field(default="", alias="META_PAGE_ID")
    meta_ig_user_id: str = Field(default="", alias="META_IG_USER_ID")
    meta_page_access_token: str = Field(default="", alias="META_PAGE_ACCESS_TOKEN")
    contentstack_api_key: str = Field(default="", alias="CONTENTSTACK_API_KEY")
    contentstack_management_token: str = Field(default="", alias="CONTENTSTACK_MANAGEMENT_TOKEN")
    contentstack_api_host: str = Field(default="https://api.contentstack.io", alias="CONTENTSTACK_API_HOST")
    contentstack_image_host: str = Field(default="https://images.contentstack.io", alias="CONTENTSTACK_IMAGE_HOST")
    contentstack_video_host: str = Field(default="https://assets.contentstack.io", alias="CONTENTSTACK_VIDEO_HOST")
    media_root: Path = Field(default=Path.home() / "Documents/Instagram Photos & Reels", alias="MEDIA_ROOT")

    data_dir: Path = Field(default=ROOT / "data", alias="DATA_DIR")
    templates_dir: Path = Field(default=ROOT / "templates", alias="TEMPLATES_DIR")

    @field_validator("llm_base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("posting_time")
    @classmethod
    def hhmm(cls, v: str) -> str:
        if not re.fullmatch(r"\d{2}:\d{2}", v):
            raise ValueError("POSTING_TIME must be HH:MM (24h).")
        hour, minute = (int(x) for x in v.split(":"))
        if hour > 23 or minute > 59:
            raise ValueError("POSTING_TIME must be a valid clock time.")
        return v

    def env_posting_days(self) -> FrozenSet[str]:
        return _parse_days(self.posting_days)

    def llm_ready(self) -> bool:
        return bool(self.llm_api_key.strip() and self.llm_model.strip() and self.llm_base_url.strip())

    def meta_ready(self) -> bool:
        return bool(
            self.meta_page_access_token.strip()
            and self.meta_page_id.strip()
            and self.meta_ig_user_id.strip()
        )

    def contentstack_ready(self) -> bool:
        return bool(self.contentstack_api_key.strip() and self.contentstack_management_token.strip())

    def public_status(self) -> dict:
        """Safe for the browser — booleans and schedule only, never secrets."""
        return {
            "llmConfigured": self.llm_ready(),
            "metaConfigured": self.meta_ready(),
            "llmModel": self.llm_model if self.llm_ready() else None,
            "envPostingDays": sorted(self.env_posting_days(), key=WEEKDAYS.index),
            "postingTime": self.posting_time,
            "postingTimezone": self.posting_timezone,
        }


def _assert_no_public_secret_leak() -> None:
    for name in _SECRET_ENV_NAMES:
        if os.environ.get(f"NEXT_PUBLIC_{name}"):
            raise RuntimeError(
                f"Refusing to start: NEXT_PUBLIC_{name} would leak a secret to clients. "
                "Put secrets only in server-side .env keys."
            )


@lru_cache
def get_settings() -> Settings:
    _assert_no_public_secret_leak()
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings


def reset_settings_cache() -> None:
    get_settings.cache_clear()
