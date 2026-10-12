"""Configuração a partir de variáveis de ambiente / `.env` (ver SPEC §4)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    trello_api_key: SecretStr
    trello_token: SecretStr
    trello_org_allowlist: Annotated[list[str], NoDecode] = Field(min_length=1)
    trello_read_only: bool = False
    trello_allow_destructive: bool = False
    trello_base_url: str = "https://api.trello.com/1"
    trello_rate_limit: int = Field(default=100, gt=0, description="Requisições por janela de 10 s (por token)")

    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_http_host: str = "127.0.0.1"
    mcp_http_port: int = 3333

    audit_log_path: Path | None = None

    @field_validator("trello_org_allowlist", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value
