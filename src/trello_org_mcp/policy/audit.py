"""Auditoria de operações de escrita em JSONL (SPEC §6.4)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trello_org_mcp.log import get_logger

log = get_logger("audit")
_SECRET_KEYS = re.compile(r"(token|key|secret|password)", re.IGNORECASE)


def _redact(args: dict[str, Any]) -> dict[str, Any]:
    return {k: ("***" if _SECRET_KEYS.search(k) else v) for k, v in args.items()}


class AuditLog:
    def __init__(self, path: Path | None):
        self.path = path

    def record(self, tool: str, args: dict[str, Any], *, ok: bool, result: str) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "tool": tool,
            "args": _redact(args),
            "ok": ok,
            "result": result[:500],
        }
        log.info("audit", **entry)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
