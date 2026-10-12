"""Registro de todas as tools (SPEC §5)."""

from __future__ import annotations

from trello_org_mcp.deps import Deps
from trello_org_mcp.tools import activity, boards, cards, members, organizations, reports, search


def register_all(deps: Deps) -> None:
    for module in (organizations, boards, members, cards, search, activity, reports):
        module.register(deps)
