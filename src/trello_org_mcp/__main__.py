"""Entrypoint: `trello-org-mcp` / `python -m trello_org_mcp`."""

from __future__ import annotations

import sys

from pydantic import ValidationError

from trello_org_mcp.config import Settings
from trello_org_mcp.log import configure_logging
from trello_org_mcp.server import build_server


def main() -> None:
    configure_logging()
    try:
        settings = Settings()
    except ValidationError as exc:
        missing = ", ".join(str(err["loc"][0]).upper() for err in exc.errors())
        print(f"Configuração inválida ou ausente: {missing}\n{exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    server = build_server(settings)
    if settings.mcp_transport == "http":
        server.run(
            "streamable-http",
            host=settings.mcp_http_host,
            port=settings.mcp_http_port,
        )
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
