from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class LocationOption(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    floors: list[int] = Field(default_factory=list)


def _parse_json_or_default(raw_value: Any, default: Any) -> Any:
    if raw_value is None:
        return default
    if isinstance(raw_value, (dict, list)):
        return raw_value
    if isinstance(raw_value, str):
        value = raw_value.strip()
        if not value:
            return default
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return default
        return parsed
    return default


def _parse_api_paths(raw_value: Any) -> dict[str, str]:
    default_paths = {
        "bridge": "/api/bridge",
    }
    parsed = _parse_json_or_default(raw_value, default_paths)
    if not isinstance(parsed, dict):
        return default_paths

    normalized: dict[str, str] = {}
    for key, value in parsed.items():
        if not isinstance(value, str):
            continue
        path = value if value.startswith("/") else f"/{value}"
        normalized[str(key)] = path

    return {**default_paths, **normalized}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )

    telegram_bot_token: SecretStr = Field(alias="TELEGRAM_BOT_TOKEN")
    java_base_url: str = Field(alias="JAVA_BASE_URL")
    # NoDecode: pydantic-settings по умолчанию сам json.loads составные поля
    # и падает с SettingsError на невалидном значении. Нам нужно, чтобы сырая
    # строка дошла до валидаторов ниже — они умеют откатываться к дефолтам
    # и разбирать не-JSON форматы (например, "111,222").
    java_api_paths: Annotated[dict[str, str], NoDecode] = Field(
        default_factory=dict, alias="JAVA_API_PATHS"
    )
    java_auth_scheme: Literal["none", "api_key", "bearer", "basic"] = Field(
        default="none",
        alias="JAVA_AUTH_SCHEME",
    )
    java_auth_secret: str | None = Field(default=None, alias="JAVA_AUTH_SECRET")
    java_api_key_header: str = Field(default="X-API-Key", alias="JAVA_API_KEY_HEADER")

    request_json_schema: str = Field(default="", alias="REQUEST_JSON_SCHEMA")
    response_json_schema: str = Field(default="", alias="RESPONSE_JSON_SCHEMA")

    locations_list: Annotated[list[LocationOption], NoDecode] = Field(
        default_factory=list, alias="LOCATIONS_LIST"
    )
    search_filters: Annotated[dict[str, Any], NoDecode] = Field(
        default_factory=dict, alias="SEARCH_FILTERS"
    )
    admin_telegram_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list, alias="ADMIN_TELEGRAM_IDS"
    )

    request_timeout_seconds: float = Field(default=8.0, alias="REQUEST_TIMEOUT_SECONDS")
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    retry_backoff_base: float = Field(default=0.6, alias="RETRY_BACKOFF_BASE")

    storage_path: str = Field(default="data/users.json", alias="STORAGE_PATH")
    log_path: str = Field(default="logs/bot.log", alias="LOG_PATH")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("java_api_paths", mode="before")
    @classmethod
    def parse_java_api_paths(cls, value: Any) -> dict[str, str]:
        return _parse_api_paths(value)

    @field_validator("locations_list", mode="before")
    @classmethod
    def parse_locations_list(cls, value: Any) -> list[dict[str, Any]]:
        parsed = _parse_json_or_default(value, [])
        if not isinstance(parsed, list):
            return []
        return parsed

    @field_validator("search_filters", mode="before")
    @classmethod
    def parse_search_filters(cls, value: Any) -> dict[str, Any]:
        parsed = _parse_json_or_default(value, {})
        if not isinstance(parsed, dict):
            return {}
        return parsed

    @field_validator("admin_telegram_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: Any) -> list[int]:
        if value is None:
            return []
        if isinstance(value, list):
            return [int(item) for item in value]
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    return []
                return [int(item) for item in parsed]
            return [int(item.strip()) for item in raw.split(",") if item.strip()]
        return []

    @property
    def bridge_path(self) -> str:
        return self.java_api_paths["bridge"]

    @property
    def duration_options(self) -> list[int]:
        default = [30, 60, 90, 120]
        value = self.search_filters.get("duration_options")
        if not isinstance(value, list):
            return default
        options: set[int] = set()
        for item in value:
            try:
                number = int(item)
            except (TypeError, ValueError):
                continue
            if number > 0:
                options.add(number)
        if not options:
            return default
        return sorted(options)

    @property
    def common_times(self) -> list[str]:
        default = ["08:00", "09:30", "11:00", "12:40", "14:00", "15:30", "17:00"]
        value = self.search_filters.get("common_times")
        if not isinstance(value, list):
            return default
        result = [str(item) for item in value if isinstance(item, (str, int))]
        return result or default

    def get_location(self, location_id: str) -> LocationOption | None:
        for location in self.locations_list:
            if location.id == location_id:
                return location
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
