from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

import redislite
from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeProfile(StrEnum):
    DEVELOPMENT = 'development'
    PRODUCTION = 'production'


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra='ignore')

    app_env: RuntimeProfile | None = Field(default=None, alias='APP_ENV')
    redis_url: str | None = Field(default=None, alias='REDIS_URL')
    redislite_dir: Path = Field(default=Path('.data/redislite'), alias='REDISLITE_DIR')

    openai_api_key: str | None = Field(default=None, alias='OPENAI_API_KEY')
    anthropic_api_key: str | None = Field(default=None, alias='ANTHROPIC_API_KEY')
    google_api_key: str | None = Field(default=None, alias='GOOGLE_API_KEY')

    @computed_field
    @property
    def profile(self) -> RuntimeProfile:
        if self.app_env is not None:
            return self.app_env
        if self.redis_url:
            return RuntimeProfile.PRODUCTION
        return RuntimeProfile.DEVELOPMENT

    @model_validator(mode='after')
    def validate_profile_requirements(self) -> AppSettings:
        if self.profile == RuntimeProfile.PRODUCTION and not self.redis_url:
            raise ValueError(
                'REDIS_URL is required when APP_ENV=production '
                'or when production profile is inferred.'
            )
        return self

    def has_any_model_key(self) -> bool:
        return bool(
            self.openai_api_key or self.anthropic_api_key or self.google_api_key
        )


class RedisRuntime:
    """Holds runtime-resolved Redis transport information."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.redis_url: str | None = settings.redis_url
        self.redislite_client: redislite.Redis | None = None

    def startup(self) -> None:
        if self.settings.profile == RuntimeProfile.PRODUCTION:
            self.redis_url = self.settings.redis_url
            return

        self.settings.redislite_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.settings.redislite_dir / 'redis.db'
        self.redislite_client = redislite.Redis(dbfilename=str(db_path))

        socket_path = self.redislite_client.socket_file
        if not socket_path:
            raise RuntimeError('redislite started without a unix socket path')

        self.redis_url = f'unix://{socket_path}'

        # Keep a canonical env var for downstream components that expect REDIS_URL.
        os.environ['REDIS_URL'] = self.redis_url

    def shutdown(self) -> None:
        if not self.redislite_client:
            return

        self.redislite_client.connection_pool.disconnect()
        self.redislite_client.shutdown(save=True, now=True)
        self.redislite_client = None


_settings_cache: AppSettings | None = None


def get_settings() -> AppSettings:
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = AppSettings()
    return _settings_cache
