from __future__ import annotations

from collections.abc import Callable

import pytest
import respx
from mcp import Client

CARD = {"id": "c1", "name": "Tarefa", "idBoard": "b1", "idList": "l1", "idMembers": [], "labels": []}


@pytest.fixture(autouse=True)
def hierarchy(trello: respx.MockRouter) -> None:
    """b1/l1/c1 pertencem à org1 (permitida); b9/l9 pertencem à org2 (fora da allowlist)."""
    trello.get("/boards/b1", params={"fields": "idOrganization"}).respond(json={"idOrganization": "org1"})
    trello.get("/boards/b9", params={"fields": "idOrganization"}).respond(json={"idOrganization": "org2"})
    trello.get("/lists/l1", params={"fields": "idBoard"}).respond(json={"idBoard": "b1"})
    trello.get("/lists/l2", params={"fields": "idBoard"}).respond(json={"idBoard": "b1"})
    trello.get("/lists/l9", params={"fields": "idBoard"}).respond(json={"idBoard": "b9"})
    trello.get("/cards/c1", params={"fields": "idBoard"}).respond(json={"idBoard": "b1"})


async def test_list_cards_requires_exactly_one_parent(connect: Callable[..., Client]) -> None:
    async with connect() as client:
        none = await client.call_tool("trello_list_cards", {})
        both = await client.call_tool("trello_list_cards", {"board_id": "b1", "list_id": "l1"})
    assert none.is_error and both.is_error


async def test_list_cards_by_board_respects_limit(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    trello.get("/boards/b1/cards/open").respond(json=[CARD, {**CARD, "id": "c2"}])
    async with connect() as client:
        result = await client.call_tool("trello_list_cards", {"board_id": "b1", "limit": 1})
    assert [c["id"] for c in result.structured_content["result"]] == ["c1"]


async def test_list_cards_by_list(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    trello.get("/lists/l1/cards").respond(json=[CARD])
    async with connect() as client:
        result = await client.call_tool("trello_list_cards", {"list_id": "l1"})
    assert result.structured_content["result"][0]["id_list"] == "l1"


async def test_get_card_with_comments_and_checklists(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    trello.get("/cards/c1", params={"checklists": "all"}).respond(
        json={
            **CARD,
            "members": [{"id": "m1", "fullName": "Ana"}],
            "checklists": [{"id": "k1", "name": "DoD", "checkItems": [{"name": "testes", "state": "complete"}]}],
            "actions": [
                {
                    "id": "a1",
                    "type": "commentCard",
                    "date": "2026-10-01T10:00:00.000Z",
                    "memberCreator": {"fullName": "Ana"},
                    "data": {"text": "feito"},
                }
            ],
        }
    )
    async with connect() as client:
        result = await client.call_tool("trello_get_card", {"card_id": "c1"})
    card = result.structured_content
    assert card["comments"][0]["author"] == "Ana"
    assert card["comments"][0]["text"] == "feito"
    assert card["checklists"][0]["check_items"][0]["state"] == "complete"


async def test_create_card(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    route = trello.post("/cards").respond(json=CARD)
    async with connect() as client:
        result = await client.call_tool(
            "trello_create_card",
            {"list_id": "l1", "name": "Tarefa", "member_ids": ["m1", "m2"], "due": "2026-10-10T12:00:00Z"},
        )
    assert not result.is_error
    params = route.calls.last.request.url.params
    assert params["idMembers"] == "m1,m2"
    assert params["due"] == "2026-10-10T12:00:00+00:00"


async def test_create_card_in_forbidden_list(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    route = trello.post("/cards").respond(json=CARD)
    async with connect() as client:
        result = await client.call_tool("trello_create_card", {"list_id": "l9", "name": "x"})
    assert result.is_error
    assert not route.called


async def test_update_card_clear_due(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    route = trello.put("/cards/c1").respond(json=CARD)
    async with connect() as client:
        await client.call_tool("trello_update_card", {"card_id": "c1", "clear_due": True, "due_complete": True})
    params = route.calls.last.request.url.params
    assert params["due"] == "null"
    assert params["dueComplete"] == "true"
    assert "name" not in params


async def test_move_card_sets_target_board(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    route = trello.put("/cards/c1").respond(json={**CARD, "idList": "l2"})
    async with connect() as client:
        result = await client.call_tool("trello_move_card", {"card_id": "c1", "list_id": "l2", "pos": "top"})
    assert result.structured_content["id_list"] == "l2"
    params = route.calls.last.request.url.params
    assert (params["idList"], params["idBoard"], params["pos"]) == ("l2", "b1", "top")


async def test_move_card_to_forbidden_board(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    route = trello.put("/cards/c1").respond(json=CARD)
    async with connect() as client:
        result = await client.call_tool("trello_move_card", {"card_id": "c1", "list_id": "l9"})
    assert result.is_error
    assert not route.called


async def test_archive_comment_and_create_list(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    archive = trello.put("/cards/c1").respond(json={**CARD, "closed": True})
    comment = trello.post("/cards/c1/actions/comments").respond(json={"id": "a9"})
    lst = trello.post("/lists").respond(json={"id": "l3", "name": "Revisão"})
    async with connect() as client:
        r1 = await client.call_tool("trello_archive_card", {"card_id": "c1"})
        r2 = await client.call_tool("trello_add_comment", {"card_id": "c1", "text": "olá"})
        r3 = await client.call_tool("trello_create_list", {"board_id": "b1", "name": "Revisão"})
    assert r1.structured_content["closed"] is True
    assert archive.calls.last.request.url.params["closed"] == "true"
    assert comment.calls.last.request.url.params["text"] == "olá"
    assert "a9" in r2.structured_content["message"]
    assert r3.structured_content["name"] == "Revisão"
    assert lst.calls.last.request.url.params["idBoard"] == "b1"


async def test_search_filters_foreign_results(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    route = trello.get("/search").respond(
        json={
            "boards": [
                {"id": "b1", "name": "ok", "idOrganization": "org1"},
                {"id": "b9", "name": "x", "idOrganization": "org2"},
            ],
            "cards": [CARD, {**CARD, "id": "c9", "idBoard": "b9"}],
        }
    )
    async with connect() as client:
        result = await client.call_tool("trello_search_org", {"query": "tarefa"})
    params = route.calls.last.request.url.params
    assert params["idOrganizations"] == "org1"
    assert params["modelTypes"] == "cards,boards"
    assert [b["id"] for b in result.structured_content["boards"]] == ["b1"]
    assert [c["id"] for c in result.structured_content["cards"]] == ["c1"]


async def test_activity_pagination(trello: respx.MockRouter, connect: Callable[..., Client]) -> None:
    def action(i: int) -> dict[str, object]:
        return {
            "id": f"a{i}",
            "type": "updateCard",
            "date": "2026-10-01T10:00:00.000Z",
            "memberCreator": {"fullName": "Ana"},
            "data": {"board": {"name": "Produto"}, "card": {"name": "Tarefa"}, "listAfter": {"name": "Feito"}},
        }

    route = trello.get("/organizations/org1/actions").respond(json=[action(1), action(2)])
    async with connect() as client:
        page = await client.call_tool(
            "trello_org_activity",
            {"org": "acme", "limit": 2, "action_types": ["updateCard"], "since": "2026-09-01T00:00:00Z"},
        )
        await client.call_tool("trello_org_activity", {"org": "acme", "limit": 3, "cursor": "a2"})
    data = page.structured_content
    assert data["next_cursor"] == "a2"
    assert data["actions"][0]["list_name"] == "Feito"
    first, second = (call.request.url.params for call in route.calls)
    assert first["filter"] == "updateCard"
    assert first["since"].startswith("2026-09-01")
    assert second["before"] == "a2"
