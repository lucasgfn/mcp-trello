"""Cliente HTTP assíncrono da API REST do Trello (autenticação, rate limit, retry)."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Iterable, Mapping
from typing import Any

import httpx
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception, stop_after_attempt

from trello_org_mcp.log import get_logger
from trello_org_mcp.trello.errors import TrelloError
from trello_org_mcp.trello.rate_limiter import TokenBucket

log = get_logger(__name__)

ParamValue = str | int | float | bool | Iterable[str] | None
Params = Mapping[str, ParamValue]


def _encode_params(params: Params | None) -> dict[str, str]:
    """Remove `None`, converte bool para `true/false` e listas para CSV (formato do Trello)."""
    encoded: dict[str, str] = {}
    for key, value in (params or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            encoded[key] = "true" if value else "false"
        elif isinstance(value, str | int | float):
            encoded[key] = str(value)
        else:
            encoded[key] = ",".join(value)
    return encoded


class TrelloClient:
    def __init__(
        self,
        api_key: str,
        token: str,
        *,
        base_url: str = "https://api.trello.com/1",
        rate_limiter: TokenBucket | None = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f'OAuth oauth_consumer_key="{api_key}", oauth_token="{token}"',
                "Accept": "application/json",
            },
        )
        self._limiter = rate_limiter or TokenBucket(100, 10.0)
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> TrelloClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    def _wait(self, state: RetryCallState) -> float:
        exc = state.outcome.exception() if state.outcome else None
        if isinstance(exc, TrelloError) and exc.retry_after is not None:
            return float(exc.retry_after)
        delay: float = self._backoff_base * 2 ** (int(state.attempt_number) - 1)
        return delay + random.uniform(0, delay / 2)

    async def request(self, method: str, path: str, params: Params | None = None) -> Any:
        """Executa a requisição com rate limit e até `max_retries` novas tentativas em 429/5xx/rede."""
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_retries + 1),
            wait=self._wait,
            retry=retry_if_exception(lambda e: isinstance(e, TrelloError) and e.retryable),
            sleep=asyncio.sleep,
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                return await self._send(method, path, params)
        raise AssertionError("unreachable")  # pragma: no cover

    async def _send(self, method: str, path: str, params: Params | None) -> Any:
        await self._limiter.acquire()
        try:
            response = await self._http.request(method, path, params=_encode_params(params))
        except httpx.TransportError as exc:
            raise TrelloError("NETWORK_ERROR", f"Falha de rede ao chamar o Trello: {type(exc).__name__}") from exc
        log.debug("trello_request", method=method, path=path, status=response.status_code)
        if response.is_error:
            error = TrelloError.from_response(response)
            log.warning("trello_error", method=method, path=path, status=response.status_code, code=error.code)
            raise error
        if not response.content:
            return None
        return response.json()

    async def get(self, path: str, params: Params | None = None) -> Any:
        return await self.request("GET", path, params)

    async def post(self, path: str, params: Params | None = None) -> Any:
        return await self.request("POST", path, params)

    async def put(self, path: str, params: Params | None = None) -> Any:
        return await self.request("PUT", path, params)

    async def delete(self, path: str, params: Params | None = None) -> Any:
        return await self.request("DELETE", path, params)
