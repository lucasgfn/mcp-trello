from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
import respx
from mcp import Client
from mcp.server.mcpserver import MCPServer

from trello_org_mcp.config import Settings
from trello_org_mcp.server import build_server
from trello_org_mcp.trello.client import TrelloClient
from trello_org_mcp.trello.rate_limiter import TokenBucket

BASE = "https://api.trello.com/1"

ORGS = [
    {"id": "org1", "name": "acme", "displayName": "ACME", "desc": "", "url": "https://trello.com/w/acme"},
    {"id": "org2", "name": "outra", "displayName": "Outra", "desc": "", "url": "https://trello.com/w/outra"},
]


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "trello_api_key": "KEY123",
        "trello_token": "TOKEN456",
        "trello_org_allowlist": "acme",
        "audit_log_path": None,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def make_client() -> TrelloClient:
    return TrelloClient("KEY123", "TOKEN456", base_url=BASE, rate_limiter=TokenBucket(10_000), backoff_base=0)


@pytest.fixture
def trello() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        router.get("/members/me/organizations").respond(json=ORGS)
        yield router


@pytest.fixture
def server_factory() -> Callable[..., MCPServer[Any]]:
    def factory(**overrides: Any) -> MCPServer[Any]:
        return build_server(make_settings(**overrides), client=make_client())

    return factory


@pytest.fixture
def connect(trello: respx.MockRouter, server_factory: Callable[..., MCPServer[Any]]) -> Callable[..., Client]:
    """`async with connect(**overrides) as client:` — cliente MCP em memória.

    Aberto dentro do próprio teste (e não num fixture assíncrono) porque a sessão usa
    cancel scopes do anyio, que precisam entrar e sair na mesma task.
    """

    def _connect(**overrides: Any) -> Client:
        return Client(server_factory(**overrides))

    return _connect
