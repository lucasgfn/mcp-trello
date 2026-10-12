"""Registro de tools com políticas aplicadas automaticamente (SPEC §6).

- `read`: sempre registrada.
- `write`: omitida quando `TRELLO_READ_ONLY=true`.
- `destructive`: só registrada com `TRELLO_ALLOW_DESTRUCTIVE=true` (e fora do read-only);
  exige `confirm=True` na chamada.

Escritas (e tentativas negadas) vão para a auditoria; erros do Trello e da allowlist
viram `ToolError`, que o SDK devolve ao modelo como resultado com `isError: true`.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from trello_org_mcp.config import Settings
from trello_org_mcp.policy.allowlist import ForbiddenOrgError
from trello_org_mcp.policy.audit import AuditLog
from trello_org_mcp.trello.errors import TrelloError

ToolKind = Literal["read", "write", "destructive"]
F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def _summarize(result: Any) -> str:
    if hasattr(result, "model_dump_json"):
        return str(result.model_dump_json())
    return repr(result)


class ToolRegistry:
    def __init__(self, mcp: MCPServer[Any], settings: Settings, audit: AuditLog):
        self.mcp = mcp
        self.settings = settings
        self.audit = audit
        self.registered: list[str] = []
        self.skipped: list[str] = []

    def enabled(self, kind: ToolKind) -> bool:
        if kind == "read":
            return True
        if self.settings.trello_read_only:
            return False
        return kind == "write" or self.settings.trello_allow_destructive

    def tool(self, kind: ToolKind, *, title: str | None = None, idempotent: bool = False) -> Callable[[F], F]:
        def decorator(fn: F) -> F:
            name = fn.__name__
            if not self.enabled(kind):
                self.skipped.append(name)
                return fn

            @functools.wraps(fn)
            async def wrapper(**kwargs: Any) -> Any:
                if kind == "destructive" and kwargs.get("confirm") is not True:
                    raise ToolError(
                        "CONFIRMATION_REQUIRED: operação destrutiva. Confirme com o usuário e "
                        "chame novamente com confirm=true."
                    )
                try:
                    result = await fn(**kwargs)
                except (ForbiddenOrgError, TrelloError) as exc:
                    if kind != "read":
                        self.audit.record(name, kwargs, ok=False, result=str(exc))
                    raise ToolError(str(exc)) from exc
                if kind != "read":
                    self.audit.record(name, kwargs, ok=True, result=_summarize(result))
                return result

            annotations = ToolAnnotations(
                title=title,
                read_only_hint=kind == "read",
                destructive_hint=kind == "destructive",
                idempotent_hint=True if kind == "read" else idempotent,
                open_world_hint=True,
            )
            self.mcp.add_tool(wrapper, name=name, title=title, annotations=annotations)
            self.registered.append(name)
            return fn

        return decorator
