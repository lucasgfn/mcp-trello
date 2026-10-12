"""Relatórios agregados da organização (SPEC §5.6).

As chamadas por board rodam em paralelo; o `TokenBucket` do cliente segura o ritmo
para não estourar o rate limit do Trello.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from pydantic import BaseModel, Field

from trello_org_mcp.deps import Deps
from trello_org_mcp.tools import fields
from trello_org_mcp.tools.boards import list_org_boards
from trello_org_mcp.tools.members import list_org_members
from trello_org_mcp.tools.organizations import OrgParam
from trello_org_mcp.trello.models import BoardSummary, Card

BoardFilter = Annotated[list[str] | None, Field(description="Restringe a estes boards; padrão: todos os abertos")]


class OverdueCard(BaseModel):
    id: str
    name: str
    board: str
    due: datetime
    days_overdue: int
    members: list[str]
    url: str | None


class OverdueReport(BaseModel):
    generated_at: datetime
    total: int
    by_member: dict[str, int]
    cards: list[OverdueCard]


class MemberLoad(BaseModel):
    member: str
    open_cards: int
    overdue_cards: int


class WorkloadReport(BaseModel):
    generated_at: datetime
    unassigned_cards: int
    members: list[MemberLoad]


class StaleBoard(BaseModel):
    id: str
    name: str
    url: str | None
    last_activity: datetime | None
    days_inactive: int | None


class StaleBoardsReport(BaseModel):
    generated_at: datetime
    threshold_days: int
    boards: list[StaleBoard]


class ListCount(BaseModel):
    list_name: str
    open_cards: int


class BoardDistribution(BaseModel):
    board_id: str
    board: str
    total_open_cards: int
    lists: list[ListCount]


class ListDistributionReport(BaseModel):
    generated_at: datetime
    boards: list[BoardDistribution]


def _now() -> datetime:
    return datetime.now(UTC)


async def _selected_boards(deps: Deps, org: str, board_ids: list[str] | None) -> list[BoardSummary]:
    boards = await list_org_boards(deps, org, "open")
    if board_ids:
        wanted = set(board_ids)
        boards = [b for b in boards if b.id in wanted]
    return boards


async def _open_cards(deps: Deps, boards: list[BoardSummary]) -> dict[str, list[Card]]:
    results = await asyncio.gather(
        *(deps.client.get(f"/boards/{b.id}/cards/open", {"fields": fields.CARD_SHORT}) for b in boards)
    )
    return {b.id: [Card.model_validate(c) for c in raw] for b, raw in zip(boards, results, strict=True)}


def _is_overdue(card: Card, now: datetime) -> bool:
    return card.due is not None and not card.due_complete and card.due < now


def register(deps: Deps) -> None:
    tool = deps.tools.tool

    async def member_names(org: str) -> dict[str, str]:
        return {m.id: m.full_name or m.username or m.id for m in await list_org_members(deps, org)}

    @tool("read", title="Relatório de cards atrasados")
    async def trello_report_overdue(org: OrgParam, board_ids: BoardFilter = None) -> OverdueReport:
        """Cards abertos com data de entrega vencida e não concluída, do mais atrasado ao menos."""
        now = _now()
        boards = await _selected_boards(deps, org, board_ids)
        cards_by_board, names = await asyncio.gather(_open_cards(deps, boards), member_names(org))
        board_names = {b.id: b.name for b in boards}
        overdue: list[OverdueCard] = []
        for board_id, cards in cards_by_board.items():
            for card in cards:
                if _is_overdue(card, now):
                    assert card.due is not None
                    overdue.append(
                        OverdueCard(
                            id=card.id,
                            name=card.name,
                            board=board_names[board_id],
                            due=card.due,
                            days_overdue=(now - card.due).days,
                            members=[names.get(m, m) for m in card.id_members],
                            url=card.url,
                        )
                    )
        overdue.sort(key=lambda c: c.due)
        by_member: Counter[str] = Counter()
        for item in overdue:
            by_member.update(item.members or ["(sem responsável)"])
        return OverdueReport(
            generated_at=now, total=len(overdue), by_member=dict(by_member.most_common()), cards=overdue
        )

    @tool("read", title="Relatório de carga por membro")
    async def trello_report_workload(org: OrgParam, board_ids: BoardFilter = None) -> WorkloadReport:
        """Quantidade de cards abertos (e atrasados) por membro da organização."""
        now = _now()
        boards = await _selected_boards(deps, org, board_ids)
        cards_by_board, names = await asyncio.gather(_open_cards(deps, boards), member_names(org))
        open_count: Counter[str] = Counter({name: 0 for name in names.values()})
        overdue_count: Counter[str] = Counter()
        unassigned = 0
        for cards in cards_by_board.values():
            for card in cards:
                if not card.id_members:
                    unassigned += 1
                for member_id in card.id_members:
                    name = names.get(member_id, member_id)
                    open_count[name] += 1
                    if _is_overdue(card, now):
                        overdue_count[name] += 1
        members = [
            MemberLoad(member=name, open_cards=count, overdue_cards=overdue_count[name])
            for name, count in open_count.most_common()
        ]
        return WorkloadReport(generated_at=now, unassigned_cards=unassigned, members=members)

    @tool("read", title="Relatório de boards inativos")
    async def trello_report_stale_boards(
        org: OrgParam,
        days: Annotated[int, Field(ge=1, description="Dias sem atividade para considerar inativo")] = 30,
    ) -> StaleBoardsReport:
        """Boards abertos sem atividade há pelo menos `days` dias."""
        now = _now()
        threshold = now - timedelta(days=days)
        stale = [
            StaleBoard(
                id=b.id,
                name=b.name,
                url=b.url,
                last_activity=b.date_last_activity,
                days_inactive=(now - b.date_last_activity).days if b.date_last_activity else None,
            )
            for b in await list_org_boards(deps, org, "open")
            if b.date_last_activity is None or b.date_last_activity < threshold
        ]
        stale.sort(key=lambda b: b.last_activity or datetime.min.replace(tzinfo=UTC))
        return StaleBoardsReport(generated_at=now, threshold_days=days, boards=stale)

    @tool("read", title="Distribuição de cards por lista")
    async def trello_report_list_distribution(org: OrgParam, board_ids: BoardFilter = None) -> ListDistributionReport:
        """Contagem de cards abertos por lista em cada board (visão de fluxo/WIP)."""
        boards = await _selected_boards(deps, org, board_ids)
        results: list[Any] = await asyncio.gather(
            *(
                deps.client.get(
                    f"/boards/{b.id}/lists",
                    {"filter": "open", "fields": "id,name", "cards": "open", "card_fields": "id"},
                )
                for b in boards
            )
        )
        distribution = []
        for board, lists in zip(boards, results, strict=True):
            counts = [ListCount(list_name=item["name"], open_cards=len(item.get("cards", []))) for item in lists]
            distribution.append(
                BoardDistribution(
                    board_id=board.id,
                    board=board.name,
                    total_open_cards=sum(c.open_cards for c in counts),
                    lists=counts,
                )
            )
        return ListDistributionReport(generated_at=_now(), boards=distribution)
