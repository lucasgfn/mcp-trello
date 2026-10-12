from __future__ import annotations

from collections.abc import Callable

import respx
from mcp import Client

BOARD = {"id": "b1", "name": "Produto", "idOrganization": "org1", "closed": False, "url": "u", "foo": "ignorado"}


async def test_get_organization_counts(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    trello.get("/organizations/org1").respond(json={"id": "org1", "name": "acme", "displayName": "ACME"})
    trello.get("/organizations/org1/boards").respond(json=[{"id": "b1"}, {"id": "b2"}])
    trello.get("/organizations/org1/members").respond(json=[{"id": "m1"}])
    async with connect() as client:
        result = await client.call_tool("trello_get_organization", {"org": "ORG1"})
    assert result.structured_content == {
        "id": "org1",
        "name": "acme",
        "display_name": "ACME",
        "desc": None,
        "url": None,
        "website": None,
        "open_board_count": 2,
        "member_count": 1,
    }


async def test_list_org_boards_passes_filter(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    route = trello.get("/organizations/org1/boards").respond(json=[BOARD])
    async with connect() as client:
        result = await client.call_tool("trello_list_org_boards", {"org": "acme", "filter": "all"})
    assert route.calls.last.request.url.params["filter"] == "all"
    board = result.structured_content["result"][0]
    assert board["id_organization"] == "org1"
    assert "foo" not in board


async def test_get_board_with_lists(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    trello.get("/boards/b1", params={"fields": "idOrganization"}).respond(json={"idOrganization": "org1"})
    trello.get("/boards/b1", params={"lists": "open"}).respond(
        json={**BOARD, "lists": [{"id": "l1", "name": "A fazer", "pos": 1}], "labels": [], "members": []}
    )
    async with connect() as client:
        result = await client.call_tool("trello_get_board", {"board_id": "b1"})
    assert not result.is_error, result.content
    assert result.structured_content["lists"][0]["name"] == "A fazer"


async def test_create_board_in_org(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    route = trello.post("/boards").respond(json=BOARD)
    async with connect() as client:
        result = await client.call_tool("trello_create_board", {"org": "acme", "name": "Produto"})
    assert not result.is_error
    params = route.calls.last.request.url.params
    assert params["idOrganization"] == "org1"
    assert params["defaultLists"] == "true"
    assert "desc" not in params


async def test_list_org_members_merges_roles(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    trello.get("/organizations/org1/members").respond(
        json=[{"id": "m1", "username": "ana", "fullName": "Ana"}, {"id": "m2", "username": "bo", "fullName": "Bo"}]
    )
    trello.get("/organizations/org1/memberships").respond(
        json=[
            {"idMember": "m1", "memberType": "admin"},
            {"idMember": "m2", "memberType": "normal", "unconfirmed": True},
        ]
    )
    async with connect() as client:
        result = await client.call_tool("trello_list_org_members", {"org": "acme"})
    members = result.structured_content["result"]
    assert [(m["full_name"], m["role"], m["unconfirmed"]) for m in members] == [
        ("Ana", "admin", False),
        ("Bo", "normal", True),
    ]


async def test_member_workload_only_org_boards(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    trello.get("/organizations/org1/boards").respond(json=[BOARD])
    trello.get("/members/ana/cards").respond(
        json=[
            {"id": "c1", "name": "Na org", "idBoard": "b1", "idList": "l1"},
            {"id": "c2", "name": "Fora", "idBoard": "outro", "idList": "l9"},
        ]
    )
    async with connect() as client:
        result = await client.call_tool("trello_get_member_workload", {"org": "acme", "member": "ana"})
    assert [c["id"] for c in result.structured_content["result"]] == ["c1"]


async def test_invite_and_set_role(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    invite = trello.put("/organizations/org1/members").respond(json={})
    role = trello.put("/organizations/org1/members/m1").respond(json={})
    async with connect() as client:
        r1 = await client.call_tool("trello_invite_org_member", {"org": "acme", "email": "x@y.com", "full_name": "X Y"})
        r2 = await client.call_tool("trello_set_org_member_role", {"org": "acme", "member_id": "m1", "role": "admin"})
    assert not r1.is_error and not r2.is_error
    assert invite.calls.last.request.url.params["type"] == "normal"
    assert role.calls.last.request.url.params["type"] == "admin"


async def test_invalid_role_rejected_by_schema(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    async with connect() as client:
        result = await client.call_tool(
            "trello_set_org_member_role", {"org": "acme", "member_id": "m1", "role": "owner"}
        )
    assert result.is_error
