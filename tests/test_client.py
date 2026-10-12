import httpx
import pytest
import respx

from tests.conftest import BASE, make_client
from trello_org_mcp.trello.client import _encode_params
from trello_org_mcp.trello.errors import TrelloError


def test_encode_params() -> None:
    assert _encode_params({"a": None, "b": True, "c": False, "d": 3, "e": ["x", "y"], "f": "z"}) == {
        "b": "true",
        "c": "false",
        "d": "3",
        "e": "x,y",
        "f": "z",
    }


@respx.mock(base_url=BASE)
async def test_success_sends_auth_header_not_query(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/boards/b1").respond(json={"id": "b1"})
    async with make_client() as client:
        assert await client.get("/boards/b1", {"fields": "id"}) == {"id": "b1"}
    request = route.calls.last.request
    assert request.headers["Authorization"] == 'OAuth oauth_consumer_key="KEY123", oauth_token="TOKEN456"'
    assert "TOKEN456" not in str(request.url)
    assert request.url.params["fields"] == "id"


@pytest.mark.parametrize(("status", "code"), [(401, "AUTH_INVALID"), (403, "FORBIDDEN"), (404, "NOT_FOUND")])
@respx.mock(base_url=BASE)
async def test_client_errors_are_mapped_without_retry(respx_mock: respx.MockRouter, status: int, code: str) -> None:
    route = respx_mock.get("/x").respond(status, text="nope")
    async with make_client() as client:
        with pytest.raises(TrelloError) as exc_info:
            await client.get("/x")
    assert exc_info.value.code == code
    assert "TOKEN456" not in str(exc_info.value)
    assert route.call_count == 1


@respx.mock(base_url=BASE)
async def test_retries_429_then_succeeds(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/x").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json=[1])]
    )
    async with make_client() as client:
        assert await client.get("/x") == [1]
    assert route.call_count == 2


@respx.mock(base_url=BASE)
async def test_5xx_gives_up_after_max_retries(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/x").respond(503)
    async with make_client() as client:
        with pytest.raises(TrelloError) as exc_info:
            await client.get("/x")
    assert exc_info.value.code == "UPSTREAM_ERROR"
    assert route.call_count == 4  # 1 tentativa + 3 retries


@respx.mock(base_url=BASE)
async def test_network_error_is_retried(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/x").mock(side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={})])
    async with make_client() as client:
        assert await client.get("/x") == {}
    assert route.call_count == 2


@respx.mock(base_url=BASE)
async def test_empty_body_returns_none(respx_mock: respx.MockRouter) -> None:
    respx_mock.delete("/x").respond(200)
    async with make_client() as client:
        assert await client.delete("/x") is None
