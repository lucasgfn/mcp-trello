from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import respx
from mcp import Client
from mcp.server.mcpserver import MCPServer

WRITE_TOOLS = {"trello_create_card", "trello_update_organization", "trello_invite_org_member"}
DESTRUCTIVE_TOOLS = {"trello_close_board", "trello_remove_org_member"}


async def _tool_names(server: MCPServer[Any]) -> set[str]:
    return {t.name for t in await server.list_tools()}


async def test_default_registers_write_but_not_destructive(server_factory: Callable[..., MCPServer[Any]]) -> None:
    names = await _tool_names(server_factory())
    assert names >= WRITE_TOOLS
    assert not DESTRUCTIVE_TOOLS & names


async def test_read_only_hides_all_writes(server_factory: Callable[..., MCPServer[Any]]) -> None:
    server = server_factory(trello_read_only=True, trello_allow_destructive=True)
    tools = await server.list_tools()
    assert tools
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)
    assert not (WRITE_TOOLS | DESTRUCTIVE_TOOLS) & {t.name for t in tools}


async def test_destructive_registered_when_allowed(server_factory: Callable[..., MCPServer[Any]]) -> None:
    tools = {t.name: t for t in await server_factory(trello_allow_destructive=True).list_tools()}
    assert tools.keys() >= DESTRUCTIVE_TOOLS
    annotations = tools["trello_remove_org_member"].annotations
    assert annotations is not None and annotations.destructive_hint is True


async def test_list_organizations_filters_by_allowlist(connect: Callable[..., Client]) -> None:
    async with connect() as mcp_client:
        result = await mcp_client.call_tool("trello_list_organizations", {})
        assert not result.is_error
        assert [o["name"] for o in result.structured_content["result"]] == ["acme"]


async def test_org_outside_allowlist_is_rejected_before_any_write(
    trello: respx.MockRouter, connect: Callable[..., Client]
) -> None:
    async with connect() as mcp_client:
        put = trello.put("/organizations/org2").respond(json={})
        result = await mcp_client.call_tool("trello_update_organization", {"org": "outra", "desc": "x"})
        assert result.is_error
        assert "FORBIDDEN_ORG" in result.content[0].text
        assert not put.called


async def test_board_outside_allowlist_is_rejected(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    async with connect() as mcp_client:
        trello.get("/boards/b9").respond(json={"id": "b9", "idOrganization": "org2"})
        result = await mcp_client.call_tool("trello_get_board", {"board_id": "b9"})
        assert result.is_error
        assert "FORBIDDEN_ORG" in result.content[0].text


async def test_unknown_card_is_reported_as_forbidden(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    async with connect() as mcp_client:
        trello.get("/cards/nope").respond(404, text="not found")
        result = await mcp_client.call_tool("trello_archive_card", {"card_id": "nope"})
        assert result.is_error
        assert "FORBIDDEN_ORG" in result.content[0].text


async def test_destructive_requires_confirm(
    trello: respx.MockRouter, server_factory: Callable[..., MCPServer[Any]]
) -> None:
    delete = trello.delete("/organizations/org1/members/m1").respond(json={})
    async with Client(server_factory(trello_allow_destructive=True)) as client:
        denied = await client.call_tool("trello_remove_org_member", {"org": "acme", "member_id": "m1"})
        assert denied.is_error
        assert "CONFIRMATION_REQUIRED" in denied.content[0].text
        assert not delete.called

        ok = await client.call_tool("trello_remove_org_member", {"org": "acme", "member_id": "m1", "confirm": True})
        assert not ok.is_error
        assert delete.called


async def test_writes_are_audited(
    trello: respx.MockRouter, server_factory: Callable[..., MCPServer[Any]], tmp_path: Path
) -> None:
    audit = tmp_path / "audit.jsonl"
    trello.put("/organizations/org1").respond(json={"id": "org1", "name": "acme", "desc": "nova"})
    async with Client(server_factory(audit_log_path=audit)) as client:
        await client.call_tool("trello_update_organization", {"org": "acme", "desc": "nova"})
        await client.call_tool("trello_update_organization", {"org": "outra", "desc": "x"})
        await client.call_tool("trello_list_organizations", {})
    entries = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [(e["tool"], e["ok"]) for e in entries] == [
        ("trello_update_organization", True),
        ("trello_update_organization", False),
    ]
    assert entries[0]["args"]["desc"] == "nova"


async def test_trello_errors_become_tool_errors(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    async with connect() as mcp_client:
        trello.get("/organizations/org1").respond(401, text="invalid token")
        trello.get("/organizations/org1/boards").respond(json=[])
        trello.get("/organizations/org1/members").respond(json=[])
        result = await mcp_client.call_tool("trello_get_organization", {"org": "acme"})
        assert result.is_error
        assert "AUTH_INVALID" in result.content[0].text
