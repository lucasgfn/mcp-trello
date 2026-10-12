"""Erros da API do Trello mapeados para códigos estáveis (SPEC §7)."""

from __future__ import annotations

import httpx

_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "AUTH_INVALID",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    429: "RATE_LIMITED",
}

_HINTS = {
    "AUTH_INVALID": "Verifique TRELLO_API_KEY e TRELLO_TOKEN.",
    "FORBIDDEN": "O token não tem permissão para este recurso.",
    "NOT_FOUND": "Recurso não encontrado ou inacessível para este token.",
    "RATE_LIMITED": "Limite de requisições do Trello atingido; tente novamente em instantes.",
    "UPSTREAM_ERROR": "O Trello retornou um erro interno; tente novamente.",
}


class TrelloError(Exception):
    def __init__(self, code: str, message: str, *, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.code in {"RATE_LIMITED", "UPSTREAM_ERROR", "NETWORK_ERROR"}

    def __str__(self) -> str:
        return f"{self.code}: {self.args[0]}"

    @classmethod
    def from_response(cls, response: httpx.Response) -> TrelloError:
        status = response.status_code
        code = _STATUS_CODES.get(status, "UPSTREAM_ERROR" if status >= 500 else "BAD_REQUEST")
        detail = response.text.strip()[:300]
        message = " ".join(
            part
            for part in (_HINTS.get(code, ""), f"(HTTP {status}: {detail})" if detail else f"(HTTP {status})")
            if part
        )
        return cls(code, message, status=status, retry_after=_parse_retry_after(response))


def _parse_retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        return None
