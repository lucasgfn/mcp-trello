"""Busca transversal na organização (SPEC §5.5)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from trello_org_mcp.deps import Deps
from trello_org_mcp.policy.allowlist import ForbiddenOrgError
from trello_org_mcp.tools import fields
from trello_org_mcp.trello.models import BoardSummary, Card, SearchResults


def register(deps: Deps) -> None:
    @deps.tools.tool("read", title="Buscar na organização")
    async def trello_search_org(
        query: Annotated[
            str,
            Field(min_length=1, description="Termos de busca (aceita operadores do Trello, ex.: @me, label:, due:)"),
        ],
        org: Annotated[
            str | None, Field(description="Restringe a uma organização; padrão: todas as permitidas")
        ] = None,
        model_types: list[Literal["cards", "boards"]] | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
        partial: Annotated[bool, Field(description="Casa prefixos de palavras")] = True,
    ) -> SearchResults:
        """Busca cards e boards nas organizações permitidas."""
        org_ids = [(await deps.allowlist.require_org(org)).id] if org else await deps.allowlist.org_ids()
        types = model_types or ["cards", "boards"]
        raw = await deps.client.get(
            "/search",
            {
                "query": query,
                "idOrganizations": org_ids,
                "modelTypes": types,
                "partial": partial,
                "cards_limit": limit,
                "boards_limit": limit,
                "card_fields": fields.CARD_SHORT,
                "board_fields": fields.BOARD,
            },
        )
        # Defesa em profundidade: descarta qualquer resultado fora das orgs permitidas.
        boards = [BoardSummary.model_validate(b) for b in raw.get("boards", []) if b.get("idOrganization") in org_ids]
        cards = []
        for c in raw.get("cards", []):
            try:
                if await deps.allowlist.require_board(c["idBoard"]) in org_ids:
                    cards.append(Card.model_validate(c))
            except ForbiddenOrgError:
                continue
        return SearchResults(boards=boards, cards=cards)
