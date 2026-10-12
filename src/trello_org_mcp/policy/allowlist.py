"""Restringe toda operação às organizações permitidas (SPEC §6.1)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from trello_org_mcp.trello.client import TrelloClient
from trello_org_mcp.trello.errors import TrelloError
from trello_org_mcp.trello.models import Organization

ORG_FIELDS = "id,name,displayName,desc,url,website"


class ForbiddenOrgError(Exception):
    """Recurso fora da allowlist. A mensagem é segura para devolver ao modelo."""


class Allowlist:
    def __init__(
        self,
        client: TrelloClient,
        entries: list[str],
        *,
        cache_ttl: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._client = client
        self._entries = {entry.strip().lower() for entry in entries if entry.strip()}
        self._orgs: dict[str, Organization] | None = None
        self._lock = asyncio.Lock()
        self._cache_ttl = cache_ttl
        self._clock = clock
        self._parent_cache: dict[str, tuple[float, str | None]] = {}

    async def orgs(self) -> list[Organization]:
        """Organizações acessíveis ao token que estão na allowlist (resolvidas uma vez)."""
        async with self._lock:
            if self._orgs is None:
                raw = await self._client.get("/members/me/organizations", {"fields": ORG_FIELDS})
                orgs = [Organization.model_validate(item) for item in raw]
                self._orgs = {
                    org.id: org for org in orgs if org.id.lower() in self._entries or org.name.lower() in self._entries
                }
        return list(self._orgs.values())

    async def org_ids(self) -> list[str]:
        return [org.id for org in await self.orgs()]

    async def require_org(self, id_or_name: str) -> Organization:
        key = id_or_name.strip().lower()
        for org in await self.orgs():
            if key in (org.id.lower(), org.name.lower()):
                return org
        raise ForbiddenOrgError(
            f"FORBIDDEN_ORG: a organização '{id_or_name}' não existe, não é acessível ou está fora da allowlist."
        )

    async def _cached_parent(self, kind: str, obj_id: str, path: str, field: str) -> str | None:
        key = f"{kind}:{obj_id}"
        cached = self._parent_cache.get(key)
        if cached and self._clock() - cached[0] < self._cache_ttl:
            return cached[1]
        try:
            raw = await self._client.get(path, {"fields": field})
        except TrelloError as exc:
            if exc.code in {"NOT_FOUND", "BAD_REQUEST", "FORBIDDEN"}:
                raise ForbiddenOrgError(
                    f"FORBIDDEN_ORG: {kind} '{obj_id}' não encontrado ou fora da allowlist."
                ) from exc
            raise
        parent: str | None = raw.get(field)
        self._parent_cache[key] = (self._clock(), parent)
        return parent

    async def require_board(self, board_id: str) -> str:
        """Garante que o board pertence a uma org permitida; devolve o id da org."""
        org_id = await self._cached_parent("board", board_id, f"/boards/{board_id}", "idOrganization")
        if org_id is None or org_id not in await self.org_ids():
            raise ForbiddenOrgError(f"FORBIDDEN_ORG: board '{board_id}' não encontrado ou fora da allowlist.")
        return org_id

    async def require_list(self, list_id: str) -> str:
        """Garante que a lista pertence a um board permitido; devolve o id do board."""
        board_id = await self._cached_parent("list", list_id, f"/lists/{list_id}", "idBoard")
        if board_id is None:
            raise ForbiddenOrgError(f"FORBIDDEN_ORG: lista '{list_id}' não encontrada.")
        await self.require_board(board_id)
        return board_id

    async def require_card(self, card_id: str) -> str:
        """Garante que o card pertence a um board permitido; devolve o id do board."""
        board_id = await self._cached_parent("card", card_id, f"/cards/{card_id}", "idBoard")
        if board_id is None:
            raise ForbiddenOrgError(f"FORBIDDEN_ORG: card '{card_id}' não encontrado.")
        await self.require_board(board_id)
        return board_id

    def forget(self, kind: str, obj_id: str) -> None:
        """Invalida o cache (ex.: card movido para outro board)."""
        self._parent_cache.pop(f"{kind}:{obj_id}", None)
