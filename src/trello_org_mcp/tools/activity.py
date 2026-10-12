"""Feed de atividade da organização (SPEC §5.5)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import Field

from trello_org_mcp.deps import Deps
from trello_org_mcp.tools.organizations import OrgParam
from trello_org_mcp.trello.models import Action, ActivityPage


def _to_action(raw: dict[str, Any]) -> Action:
    data = raw.get("data") or {}
    return Action(
        id=raw["id"],
        type=raw["type"],
        date=raw["date"],
        author=(raw.get("memberCreator") or {}).get("fullName"),
        board_name=(data.get("board") or {}).get("name"),
        list_name=(data.get("list") or data.get("listAfter") or {}).get("name"),
        card_name=(data.get("card") or {}).get("name"),
        text=data.get("text"),
    )


async def org_activity(
    deps: Deps,
    org: str,
    *,
    since: datetime | None = None,
    before: datetime | None = None,
    action_types: list[str] | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> ActivityPage:
    allowed = await deps.allowlist.require_org(org)
    raw = await deps.client.get(
        f"/organizations/{allowed.id}/actions",
        {
            "filter": action_types,
            "since": since.isoformat() if since else None,
            "before": cursor or (before.isoformat() if before else None),
            "limit": limit,
            "fields": "id,type,date,data",
            "memberCreator_fields": "fullName",
        },
    )
    actions = [_to_action(item) for item in raw]
    next_cursor = actions[-1].id if len(actions) == limit else None
    return ActivityPage(actions=actions, next_cursor=next_cursor)


def register(deps: Deps) -> None:
    @deps.tools.tool("read", title="Atividade da organização")
    async def trello_org_activity(
        org: OrgParam,
        since: Annotated[datetime | None, Field(description="Apenas ações a partir desta data (ISO 8601)")] = None,
        before: Annotated[datetime | None, Field(description="Apenas ações anteriores a esta data (ISO 8601)")] = None,
        action_types: Annotated[
            list[str] | None, Field(description="Tipos de ação, ex.: createCard, updateCard, commentCard")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=1000)] = 50,
        cursor: Annotated[str | None, Field(description="`next_cursor` da página anterior")] = None,
    ) -> ActivityPage:
        """Feed de ações da organização (mais recentes primeiro), paginado por cursor."""
        return await org_activity(
            deps, org, since=since, before=before, action_types=action_types, limit=limit, cursor=cursor
        )
