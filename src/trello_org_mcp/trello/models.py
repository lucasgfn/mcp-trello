"""Modelos Pydantic enxutos (SPEC RNF06).

Aceitam o JSON do Trello (camelCase, ex.: `idOrganization`) convertendo as chaves para
snake_case antes da validação; schema e saída das tools ficam em snake_case.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_snake


class TrelloModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _snake_case_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {to_snake(key) if isinstance(key, str) else key: value for key, value in data.items()}
        return data


class Organization(TrelloModel):
    id: str
    name: str
    display_name: str | None = None
    desc: str | None = None
    url: str | None = None
    website: str | None = None


class OrganizationDetail(Organization):
    open_board_count: int
    member_count: int


class Label(TrelloModel):
    id: str
    name: str | None = None
    color: str | None = None


class TrelloList(TrelloModel):
    id: str
    name: str
    closed: bool = False
    pos: float | None = None


class MemberRef(TrelloModel):
    id: str
    username: str | None = None
    full_name: str | None = None


class BoardSummary(TrelloModel):
    id: str
    name: str
    desc: str | None = None
    closed: bool = False
    url: str | None = None
    id_organization: str | None = None
    date_last_activity: datetime | None = None


class Board(BoardSummary):
    lists: list[TrelloList] = Field(default_factory=list)
    labels: list[Label] = Field(default_factory=list)
    members: list[MemberRef] = Field(default_factory=list)


class OrgMember(MemberRef):
    role: Literal["admin", "normal", "unknown"] = "unknown"
    unconfirmed: bool = False
    deactivated: bool = False


class Card(TrelloModel):
    id: str
    name: str
    desc: str | None = None
    closed: bool = False
    id_board: str
    id_list: str
    id_members: list[str] = Field(default_factory=list)
    labels: list[Label] = Field(default_factory=list)
    due: datetime | None = None
    due_complete: bool = False
    url: str | None = None
    date_last_activity: datetime | None = None


class CheckItem(TrelloModel):
    name: str
    state: str


class Checklist(TrelloModel):
    id: str
    name: str
    check_items: list[CheckItem] = Field(default_factory=list)


class Comment(BaseModel):
    id: str
    author: str | None
    date: datetime
    text: str


class CardDetail(Card):
    members: list[MemberRef] = Field(default_factory=list)
    checklists: list[Checklist] = Field(default_factory=list)
    comments: list[Comment] = Field(default_factory=list)


class Action(BaseModel):
    id: str
    type: str
    date: datetime
    author: str | None = None
    board_name: str | None = None
    list_name: str | None = None
    card_name: str | None = None
    text: str | None = None


class ActivityPage(BaseModel):
    actions: list[Action]
    next_cursor: str | None = Field(
        default=None, description="Passe como `cursor` para buscar ações mais antigas; nulo quando acabou."
    )


class SearchResults(BaseModel):
    boards: list[BoardSummary]
    cards: list[Card]


class InviteResult(BaseModel):
    org_id: str
    email: str
    role: str
    invited: bool = True


class OperationResult(BaseModel):
    ok: bool = True
    message: str
