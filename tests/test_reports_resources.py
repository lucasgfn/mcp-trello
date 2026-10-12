from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from mcp import Client
from mcp.server.mcpserver import MCPServer

NOW = datetime.now(UTC)


def iso(delta_days: float) -> str:
    return (NOW + timedelta(days=delta_days)).isoformat().replace("+00:00", "Z")


@pytest.fixture(autouse=True)
def org_data(trello: respx.MockRouter) -> None:
    trello.get("/organizations/org1/boards").respond(
        json=[
            {"id": "b1", "name": "Produto", "idOrganization": "org1", "dateLastActivity": iso(-1)},
            {"id": "b2", "name": "Legado", "idOrganization": "org1", "dateLastActivity": iso(-90)},
        ]
    )
    trello.get("/organizations/org1/members").respond(
        json=[{"id": "m1", "fullName": "Ana"}, {"id": "m2", "fullName": "Bo"}, {"id": "m3", "fullName": "Cid"}]
    )
    trello.get("/organizations/org1/memberships").respond(json=[])
    trello.get("/boards/b1/cards/open").respond(
        json=[
            {"id": "c1", "name": "Atrasado 5d", "idBoard": "b1", "idList": "l1", "idMembers": ["m1"], "due": iso(-5)},
            {
                "id": "c2",
                "name": "Concluído",
                "idBoard": "b1",
                "idList": "l1",
                "idMembers": ["m1"],
                "due": iso(-5),
                "dueComplete": True,
            },
            {"id": "c3", "name": "Futuro", "idBoard": "b1", "idList": "l2", "idMembers": ["m2"], "due": iso(3)},
        ]
    )
    trello.get("/boards/b2/cards/open").respond(
        json=[{"id": "c4", "name": "Atrasado 10d", "idBoard": "b2", "idList": "l3", "idMembers": [], "due": iso(-10)}]
    )


async def test_overdue_report(connect: Callable[..., Client]) -> None:
    async with connect() as client:
        result = await client.call_tool("trello_report_overdue", {"org": "acme"})
    report = result.structured_content
    assert report["total"] == 2
    assert [c["id"] for c in report["cards"]] == ["c4", "c1"]
    assert report["cards"][1]["members"] == ["Ana"]
    assert report["cards"][0]["days_overdue"] >= 9
    assert report["by_member"] == {"Ana": 1, "(sem responsável)": 1}


async def test_overdue_report_board_filter(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    async with connect() as client:
        result = await client.call_tool("trello_report_overdue", {"org": "acme", "board_ids": ["b1"]})
    assert [c["id"] for c in result.structured_content["cards"]] == ["c1"]
    assert all("/boards/b2/" not in str(call.request.url) for call in trello.calls)


async def test_workload_report(connect: Callable[..., Client]) -> None:
    async with connect() as client:
        result = await client.call_tool("trello_report_workload", {"org": "acme"})
    report = result.structured_content
    assert report["unassigned_cards"] == 1
    loads = {m["member"]: (m["open_cards"], m["overdue_cards"]) for m in report["members"]}
    assert loads == {"Ana": (2, 1), "Bo": (1, 0), "Cid": (0, 0)}


async def test_stale_boards_report(connect: Callable[..., Client]) -> None:
    async with connect() as client:
        result = await client.call_tool("trello_report_stale_boards", {"org": "acme", "days": 30})
    boards = result.structured_content["boards"]
    assert [b["name"] for b in boards] == ["Legado"]
    assert boards[0]["days_inactive"] >= 89


async def test_list_distribution_report(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    trello.get("/boards/b1/lists").respond(
        json=[
            {"id": "l1", "name": "A fazer", "cards": [{"id": "c1"}, {"id": "c2"}]},
            {"id": "l2", "name": "Feito", "cards": []},
        ]
    )
    trello.get("/boards/b2/lists").respond(json=[{"id": "l3", "name": "Backlog", "cards": [{"id": "c4"}]}])
    async with connect() as client:
        result = await client.call_tool("trello_report_list_distribution", {"org": "acme"})
    boards = {b["board"]: b for b in result.structured_content["boards"]}
    assert boards["Produto"]["total_open_cards"] == 2
    assert boards["Produto"]["lists"] == [
        {"list_name": "A fazer", "open_cards": 2},
        {"list_name": "Feito", "open_cards": 0},
    ]
    assert boards["Legado"]["total_open_cards"] == 1


async def test_resources(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    async with connect() as client:
        templates = await client.list_resource_templates()
        result = await client.read_resource("trello://org/acme/boards")
        forbidden_error: Exception | None = None
        try:
            forbidden = await client.read_resource("trello://org/outra/members")
        except Exception as exc:  # o SDK pode levantar MCPError para ResourceError
            forbidden_error = exc
        else:
            forbidden_error = None if forbidden.contents else AssertionError("vazio")
    assert {t.uri_template for t in templates.resource_templates} >= {
        "trello://org/{org_id}",
        "trello://org/{org_id}/boards",
        "trello://org/{org_id}/members",
        "trello://board/{board_id}",
    }
    boards = json.loads(result.contents[0].text)
    assert [b["name"] for b in boards] == ["Produto", "Legado"]
    assert forbidden_error is not None and "FORBIDDEN_ORG" in str(forbidden_error)


async def test_prompts(connect: Callable[..., Client]) -> None:
    async with connect() as client:
        prompts = {p.name for p in (await client.list_prompts()).prompts}
        prompt = await client.get_prompt("triage_overdue", {"org": "acme"})
    assert prompts == {"weekly_org_summary", "triage_overdue"}
    assert "trello_report_overdue" in prompt.messages[0].content.text


async def test_healthz(server_factory: Callable[..., MCPServer[Any]]) -> None:
    app = server_factory().streamable_http_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as http:
        response = await http.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
