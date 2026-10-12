"""Tools de boards (SPEC §5.2)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from trello_org_mcp.deps import Deps
from trello_org_mcp.tools import fields
from trello_org_mcp.tools.organizations import OrgParam
from trello_org_mcp.trello.models import Board, BoardSummary

BoardParam = Annotated[str, Field(description="ID do board")]


async def list_org_boards(deps: Deps, org: str, filter: str = "open") -> list[BoardSummary]:
    allowed = await deps.allowlist.require_org(org)
    raw = await deps.client.get(f"/organizations/{allowed.id}/boards", {"filter": filter, "fields": fields.BOARD})
    return [BoardSummary.model_validate(item) for item in raw]


async def get_board(deps: Deps, board_id: str) -> Board:
    await deps.allowlist.require_board(board_id)
    raw = await deps.client.get(
        f"/boards/{board_id}",
        {
            "fields": fields.BOARD,
            "lists": "open",
            "list_fields": fields.LIST,
            "labels": "all",
            "label_fields": fields.LABEL,
            "members": "all",
            "member_fields": fields.MEMBER,
        },
    )
    return Board.model_validate(raw)


def register(deps: Deps) -> None:
    tool = deps.tools.tool

    @tool("read", title="Listar boards da organização")
    async def trello_list_org_boards(
        org: OrgParam,
        filter: Literal["open", "closed", "all"] = "open",
    ) -> list[BoardSummary]:
        """Lista os boards de uma organização (abertos por padrão)."""
        return await list_org_boards(deps, org, filter)

    @tool("read", title="Detalhes do board")
    async def trello_get_board(board_id: BoardParam) -> Board:
        """Board com suas listas abertas, labels e membros."""
        return await get_board(deps, board_id)

    @tool("write", title="Criar board")
    async def trello_create_board(
        org: OrgParam,
        name: str,
        desc: str | None = None,
        default_lists: Annotated[bool, Field(description="Criar listas padrão (To Do/Doing/Done)")] = True,
    ) -> BoardSummary:
        """Cria um board dentro da organização."""
        allowed = await deps.allowlist.require_org(org)
        raw = await deps.client.post(
            "/boards",
            {"name": name, "desc": desc, "idOrganization": allowed.id, "defaultLists": default_lists},
        )
        return BoardSummary.model_validate(raw)

    @tool("destructive", title="Fechar board", idempotent=True)
    async def trello_close_board(board_id: BoardParam, confirm: bool = False) -> BoardSummary:
        """Fecha (arquiva) um board. Destrutivo: exige confirm=true após confirmação do usuário."""
        await deps.allowlist.require_board(board_id)
        raw = await deps.client.put(f"/boards/{board_id}", {"closed": True})
        return BoardSummary.model_validate(raw)
