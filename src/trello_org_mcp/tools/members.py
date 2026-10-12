"""Tools de membros da organização (SPEC §5.3)."""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from pydantic import Field

from trello_org_mcp.deps import Deps
from trello_org_mcp.tools import fields
from trello_org_mcp.tools.boards import list_org_boards
from trello_org_mcp.tools.organizations import OrgParam
from trello_org_mcp.trello.models import Card, InviteResult, OperationResult, OrgMember

MemberParam = Annotated[str, Field(description="ID do membro (ou username, quando indicado)")]
Role = Literal["admin", "normal"]


async def list_org_members(deps: Deps, org: str) -> list[OrgMember]:
    allowed = await deps.allowlist.require_org(org)
    members, memberships = await asyncio.gather(
        deps.client.get(f"/organizations/{allowed.id}/members", {"fields": fields.MEMBER}),
        deps.client.get(f"/organizations/{allowed.id}/memberships", {"filter": "all"}),
    )
    by_member = {m["idMember"]: m for m in memberships}
    result = []
    for member in members:
        membership = by_member.get(member["id"], {})
        role = membership.get("memberType")
        result.append(
            OrgMember.model_validate(
                {
                    **member,
                    "role": role if role in ("admin", "normal") else "unknown",
                    "unconfirmed": membership.get("unconfirmed", False),
                    "deactivated": membership.get("deactivated", False),
                }
            )
        )
    return result


def register(deps: Deps) -> None:
    tool = deps.tools.tool

    @tool("read", title="Listar membros da organização")
    async def trello_list_org_members(org: OrgParam) -> list[OrgMember]:
        """Membros da organização com papel (admin/normal) e status."""
        return await list_org_members(deps, org)

    @tool("read", title="Carga de trabalho do membro")
    async def trello_get_member_workload(
        org: OrgParam,
        member: Annotated[str, Field(description="ID ou username do membro")],
    ) -> list[Card]:
        """Cards abertos atribuídos ao membro, restritos aos boards da organização."""
        boards = await list_org_boards(deps, org, "open")
        board_ids = {b.id for b in boards}
        raw = await deps.client.get(f"/members/{member}/cards", {"filter": "open", "fields": fields.CARD_SHORT})
        return [Card.model_validate(c) for c in raw if c.get("idBoard") in board_ids]

    @tool("write", title="Convidar membro")
    async def trello_invite_org_member(
        org: OrgParam,
        email: str,
        full_name: str,
        role: Role = "normal",
    ) -> InviteResult:
        """Convida uma pessoa (por e-mail) para a organização. Requer que o token seja admin da org."""
        allowed = await deps.allowlist.require_org(org)
        await deps.client.put(
            f"/organizations/{allowed.id}/members",
            {"email": email, "fullName": full_name, "type": role},
        )
        return InviteResult(org_id=allowed.id, email=email, role=role)

    @tool("write", title="Alterar papel do membro", idempotent=True)
    async def trello_set_org_member_role(org: OrgParam, member_id: MemberParam, role: Role) -> OperationResult:
        """Define o papel (admin/normal) de um membro na organização."""
        allowed = await deps.allowlist.require_org(org)
        await deps.client.put(f"/organizations/{allowed.id}/members/{member_id}", {"type": role})
        return OperationResult(message=f"Membro {member_id} agora é '{role}' em {allowed.name}.")

    @tool("destructive", title="Remover membro", idempotent=True)
    async def trello_remove_org_member(org: OrgParam, member_id: MemberParam, confirm: bool = False) -> OperationResult:
        """Remove um membro da organização. Destrutivo: exige confirm=true após confirmação do usuário."""
        allowed = await deps.allowlist.require_org(org)
        await deps.client.delete(f"/organizations/{allowed.id}/members/{member_id}")
        return OperationResult(message=f"Membro {member_id} removido de {allowed.name}.")
