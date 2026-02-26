from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field, computed_field, model_validator
from pydantic_ai.models import KnownModelName
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeProfile(StrEnum):
    DEVELOPMENT = 'development'
    PRODUCTION = 'production'


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra='ignore')

    app_env: RuntimeProfile | None = Field(default=None, alias='APP_ENV')
    redis_url: str = Field(default='redis://localhost:6379', alias='REDIS_URL')
    taskiq_queue_name: str = Field(default='chatbot-runs', alias='TASKIQ_QUEUE_NAME')
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
        if self.database_url:
            return RuntimeProfile.PRODUCTION
        return RuntimeProfile.DEVELOPMENT

    @model_validator(mode='after')
    def validate_profile_requirements(self) -> AppSettings:
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

    def has_any_model_key(self) -> bool:
        return bool(self.available_models())


_settings_cache: AppSettings | None = None


def get_settings() -> AppSettings:
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = AppSettings()
    return _settings_cache
