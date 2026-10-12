"""Tools de organização (SPEC §5.1)."""

from __future__ import annotations

import asyncio
from typing import Annotated

from pydantic import Field

from trello_org_mcp.deps import Deps
from trello_org_mcp.tools import fields
from trello_org_mcp.trello.models import Organization, OrganizationDetail

OrgParam = Annotated[str, Field(description="ID ou nome curto (`name`) da organização")]


async def get_organization(deps: Deps, org: str) -> OrganizationDetail:
    allowed = await deps.allowlist.require_org(org)
    raw, boards, members = await asyncio.gather(
        deps.client.get(f"/organizations/{allowed.id}", {"fields": fields.ORG}),
        deps.client.get(f"/organizations/{allowed.id}/boards", {"filter": "open", "fields": "id"}),
        deps.client.get(f"/organizations/{allowed.id}/members", {"fields": "id"}),
    )
    return OrganizationDetail.model_validate({**raw, "open_board_count": len(boards), "member_count": len(members)})


def register(deps: Deps) -> None:
    tool = deps.tools.tool

    @tool("read", title="Listar organizações")
    async def trello_list_organizations() -> list[Organization]:
        """Lista as organizações (Workspaces) do Trello que este servidor pode acessar."""
        return await deps.allowlist.orgs()

    @tool("read", title="Detalhes da organização")
    async def trello_get_organization(org: OrgParam) -> OrganizationDetail:
        """Detalhes de uma organização: nome, descrição, URL, nº de boards abertos e de membros."""
        return await get_organization(deps, org)

    @tool("write", title="Atualizar organização", idempotent=True)
    async def trello_update_organization(
        org: OrgParam,
        display_name: str | None = None,
        desc: str | None = None,
        website: str | None = None,
    ) -> Organization:
        """Atualiza nome de exibição, descrição e/ou site da organização (apenas campos informados)."""
        allowed = await deps.allowlist.require_org(org)
        raw = await deps.client.put(
            f"/organizations/{allowed.id}",
            {"displayName": display_name, "desc": desc, "website": website},
        )
        return Organization.model_validate(raw)
