"""Fluxo completo contra a API real do Trello (SPEC Passo 13).

Rode com: TRELLO_E2E=1 uv run pytest -m e2e
Usa TRELLO_API_KEY/TRELLO_TOKEN/TRELLO_ORG_ALLOWLIST do ambiente (ou .env), cria um board
temporário na primeira organização permitida e o apaga no final.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from mcp import Client

from trello_org_mcp.config import Settings
from trello_org_mcp.server import build_server
from trello_org_mcp.trello.client import TrelloClient

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("TRELLO_E2E") != "1", reason="defina TRELLO_E2E=1 para rodar"),
]


def _data(result: Any) -> Any:
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def test_full_write_flow() -> None:
    settings = Settings()
    settings.trello_read_only = False
    cleanup = TrelloClient(settings.trello_api_key.get_secret_value(), settings.trello_token.get_secret_value())
    board_id: str | None = None
    try:
        async with Client(build_server(settings)) as client:
            org = _data(await client.call_tool("trello_list_organizations", {}))["result"][0]
            board = _data(
                await client.call_tool(
                    "trello_create_board",
                    {"org": org["id"], "name": f"mcp-e2e-{uuid.uuid4().hex[:8]}", "default_lists": False},
                )
            )
            board_id = board["id"]
            todo = _data(await client.call_tool("trello_create_list", {"board_id": board_id, "name": "A fazer"}))
            done = _data(await client.call_tool("trello_create_list", {"board_id": board_id, "name": "Feito"}))
            card = _data(await client.call_tool("trello_create_card", {"list_id": todo["id"], "name": "Card e2e"}))
            moved = _data(await client.call_tool("trello_move_card", {"card_id": card["id"], "list_id": done["id"]}))
            assert moved["id_list"] == done["id"]
            _data(await client.call_tool("trello_add_comment", {"card_id": card["id"], "text": "comentário e2e"}))
            detail = _data(await client.call_tool("trello_get_card", {"card_id": card["id"]}))
            assert detail["comments"][0]["text"] == "comentário e2e"
            archived = _data(await client.call_tool("trello_archive_card", {"card_id": card["id"]}))
            assert archived["closed"] is True
            dist = _data(
                await client.call_tool("trello_report_list_distribution", {"org": org["id"], "board_ids": [board_id]})
            )
            assert dist["boards"][0]["total_open_cards"] == 0
    finally:
        if board_id:
            await cleanup.delete(f"/boards/{board_id}")
        await cleanup.aclose()
