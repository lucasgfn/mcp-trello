"""Dependências compartilhadas por tools, resources e prompts."""

from __future__ import annotations

from dataclasses import dataclass

from trello_org_mcp.config import Settings
from trello_org_mcp.policy.allowlist import Allowlist
from trello_org_mcp.policy.guard import ToolRegistry
from trello_org_mcp.trello.client import TrelloClient


@dataclass
class Deps:
    settings: Settings
    client: TrelloClient
    allowlist: Allowlist
    tools: ToolRegistry
