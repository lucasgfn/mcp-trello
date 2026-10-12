import pytest
from pydantic import ValidationError

from tests.conftest import make_settings


def test_parses_csv_allowlist() -> None:
    settings = make_settings(trello_org_allowlist=" acme, org2 ,,")
    assert settings.trello_org_allowlist == ["acme", "org2"]
    assert settings.trello_read_only is False
    assert settings.mcp_transport == "stdio"
    assert "TOKEN456" not in repr(settings)


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from trello_org_mcp.config import Settings

    monkeypatch.setenv("TRELLO_API_KEY", "k")
    monkeypatch.setenv("TRELLO_TOKEN", "t")
    monkeypatch.setenv("TRELLO_ORG_ALLOWLIST", "a,b")
    monkeypatch.setenv("TRELLO_READ_ONLY", "true")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.trello_org_allowlist == ["a", "b"]
    assert settings.trello_read_only is True


def test_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    from trello_org_mcp.config import Settings

    for var in ("TRELLO_API_KEY", "TRELLO_TOKEN", "TRELLO_ORG_ALLOWLIST"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_invalid_values() -> None:
    with pytest.raises(ValidationError):
        make_settings(trello_org_allowlist="")
    with pytest.raises(ValidationError):
        make_settings(mcp_transport="websocket")
