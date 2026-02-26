from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

import redislite
from pydantic import Field, computed_field, model_validator
from pydantic_ai.models import KnownModelName
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.connection import UnixDomainSocketConnection


class RuntimeProfile(StrEnum):
    DEVELOPMENT = 'development'
    PRODUCTION = 'production'


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra='ignore')

    app_env: RuntimeProfile | None = Field(default=None, alias='APP_ENV')
    redis_url: str | None = Field(default=None, alias='REDIS_URL')
    taskiq_queue_name: str = Field(default='chatbot-runs', alias='TASKIQ_QUEUE_NAME')
    redislite_dir: Path = Field(default=Path('.data/redislite'), alias='REDISLITE_DIR')
    database_url: str | None = Field(default=None, alias='DATABASE_URL')
    sqlite_db_path: Path = Field(
        default=Path('.data/chatbot.db'),
        alias='SQLITE_DB_PATH',
    )

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
        if self.profile == RuntimeProfile.PRODUCTION and not self.database_url:
            raise ValueError(
                'DATABASE_URL is required when APP_ENV=production '
                'or when production profile is inferred.'
            )
        return self

    @computed_field
    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url

        return f'sqlite:///{self.sqlite_db_path}'

    def available_models(self) -> dict[str, KnownModelName | str]:
        models: dict[str, KnownModelName | str] = {}

        if self.anthropic_api_key:
            models['Claude Sonnet 4.5'] = 'anthropic:claude-haiku-4-5'
        if self.openai_api_key:
            models['GPT 5 Nano'] = 'openai-responses:gpt-5-nano'
            models['GPT 5 Mini'] = 'openai-responses:gpt-5-mini'
            models['GPT 5'] = 'openai-responses:gpt-5'
        if self.google_api_key:
            models['Gemini 2.5 Pro'] = 'google-gla:gemini-3-flash-preview'

        return models

    @computed_field
    @property
    def taskiq_redis_url(self) -> str:
        """Resolve the Redis URL used by Taskiq.

        In production, REDIS_URL is required and returned directly.
        In development, this value is filled after RedisRuntime starts redislite.
        """
        if self.redis_url:
            return self.redis_url
        # Development fallback; runtime startup computes and exports REDIS_URL.
        return os.environ.get('REDIS_URL', '')

    def has_any_model_key(self) -> bool:
        return bool(self.available_models())


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

        # redislite + redis-py compatibility: ensure unix socket connections have a
        # default port attribute so logging paths don't crash.
        if not hasattr(UnixDomainSocketConnection, 'port'):
            UnixDomainSocketConnection.port = 0  # type: ignore[attr-defined]

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
