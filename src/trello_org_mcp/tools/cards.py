"""Tools de listas e cards (SPEC §5.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from trello_org_mcp.deps import Deps
from trello_org_mcp.tools import fields
from trello_org_mcp.tools.boards import BoardParam
from trello_org_mcp.trello.models import Card, CardDetail, Comment, OperationResult, TrelloList

CardParam = Annotated[str, Field(description="ID do card")]
ListParam = Annotated[str, Field(description="ID da lista")]
Position = Annotated[str | None, Field(description="'top', 'bottom' ou número positivo")]
Limit = Annotated[int, Field(ge=1, le=1000, description="Máximo de itens retornados")]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _csv(values: list[str] | None) -> str | None:
    return None if values is None else ",".join(values)


def _card_detail(raw: dict[str, Any]) -> CardDetail:
    comments = [
        Comment(
            id=action["id"],
            author=(action.get("memberCreator") or {}).get("fullName"),
            date=action["date"],
            text=(action.get("data") or {}).get("text", ""),
        )
        for action in raw.get("actions", [])
        if action.get("type") == "commentCard"
    ]
    return CardDetail.model_validate({**raw, "comments": comments})


def register(deps: Deps) -> None:
    tool = deps.tools.tool
    allow = deps.allowlist

    @tool("read", title="Listar cards")
    async def trello_list_cards(
        board_id: Annotated[str | None, Field(description="ID do board (informe board_id ou list_id)")] = None,
        list_id: Annotated[str | None, Field(description="ID da lista (informe board_id ou list_id)")] = None,
        filter: Literal["open", "closed", "all"] = "open",
        limit: Limit = 100,
    ) -> list[Card]:
        """Lista cards de um board ou de uma lista."""
        if (board_id is None) == (list_id is None):
            raise ToolError("Informe exatamente um entre board_id e list_id.")
        if list_id is not None:
            await allow.require_list(list_id)
            raw = await deps.client.get(f"/lists/{list_id}/cards", {"filter": filter, "fields": fields.CARD_SHORT})
        else:
            await allow.require_board(board_id)  # type: ignore[arg-type]
            raw = await deps.client.get(f"/boards/{board_id}/cards/{filter}", {"fields": fields.CARD_SHORT})
        return [Card.model_validate(c) for c in raw[:limit]]

    @tool("read", title="Detalhes do card")
    async def trello_get_card(card_id: CardParam) -> CardDetail:
        """Card com membros, checklists e os últimos 50 comentários."""
        await allow.require_card(card_id)
        raw = await deps.client.get(
            f"/cards/{card_id}",
            {
                "fields": fields.CARD,
                "members": True,
                "member_fields": fields.MEMBER,
                "checklists": "all",
                "checklist_fields": "id,name",
                "actions": "commentCard",
                "actions_limit": 50,
                "action_memberCreator_fields": "fullName",
            },
        )
        return _card_detail(raw)

    @tool("write", title="Criar card")
    async def trello_create_card(
        list_id: ListParam,
        name: str,
        desc: str | None = None,
        due: datetime | None = None,
        member_ids: list[str] | None = None,
        label_ids: list[str] | None = None,
        pos: Position = None,
    ) -> Card:
        """Cria um card em uma lista."""
        await allow.require_list(list_id)
        raw = await deps.client.post(
            "/cards",
            {
                "idList": list_id,
                "name": name,
                "desc": desc,
                "due": _iso(due),
                "idMembers": _csv(member_ids),
                "idLabels": _csv(label_ids),
                "pos": pos,
            },
        )
        return Card.model_validate(raw)

    @tool("write", title="Atualizar card", idempotent=True)
    async def trello_update_card(
        card_id: CardParam,
        name: str | None = None,
        desc: str | None = None,
        due: datetime | None = None,
        clear_due: Annotated[bool, Field(description="Remove a data de entrega")] = False,
        due_complete: bool | None = None,
        member_ids: Annotated[list[str] | None, Field(description="Substitui os membros do card")] = None,
        label_ids: Annotated[list[str] | None, Field(description="Substitui as labels do card")] = None,
    ) -> Card:
        """Atualiza campos de um card (apenas os informados)."""
        await allow.require_card(card_id)
        raw = await deps.client.put(
            f"/cards/{card_id}",
            {
                "name": name,
                "desc": desc,
                "due": "null" if clear_due else _iso(due),
                "dueComplete": due_complete,
                "idMembers": _csv(member_ids),
                "idLabels": _csv(label_ids),
            },
        )
        return Card.model_validate(raw)

    @tool("write", title="Mover card", idempotent=True)
    async def trello_move_card(card_id: CardParam, list_id: ListParam, pos: Position = None) -> Card:
        """Move um card para outra lista (inclusive em outro board da organização permitida)."""
        await allow.require_card(card_id)
        target_board = await allow.require_list(list_id)
        raw = await deps.client.put(f"/cards/{card_id}", {"idList": list_id, "idBoard": target_board, "pos": pos})
        allow.forget("card", card_id)
        return Card.model_validate(raw)

    @tool("write", title="Arquivar card", idempotent=True)
    async def trello_archive_card(card_id: CardParam) -> Card:
        """Arquiva um card (reversível pela interface do Trello)."""
        await allow.require_card(card_id)
        raw = await deps.client.put(f"/cards/{card_id}", {"closed": True})
        return Card.model_validate(raw)

    @tool("write", title="Comentar no card")
    async def trello_add_comment(card_id: CardParam, text: str) -> OperationResult:
        """Adiciona um comentário a um card."""
        await allow.require_card(card_id)
        raw = await deps.client.post(f"/cards/{card_id}/actions/comments", {"text": text})
        return OperationResult(message=f"Comentário {raw.get('id')} criado.")

    @tool("write", title="Criar lista")
    async def trello_create_list(board_id: BoardParam, name: str, pos: Position = None) -> TrelloList:
        """Cria uma lista em um board."""
        await allow.require_board(board_id)
        raw = await deps.client.post("/lists", {"idBoard": board_id, "name": name, "pos": pos})
        return TrelloList.model_validate(raw)
