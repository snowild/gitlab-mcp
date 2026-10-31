import inspect
from unittest.mock import patch

import pytest
import requests

import gitlab_mcp.gitlab_client as gc
from tests.conftest import ENZUS, LARVATA, TWO, write_creds
from tests.unit.test_client_routing import ok


@pytest.fixture
def server(monkeypatch, tmp_path):
    p = tmp_path / "creds.json"
    monkeypatch.setenv("GITLAB_TARGETS_JSON", TWO)
    monkeypatch.setenv("GITLAB_CREDENTIALS_FILE", str(p))
    gc.reload_client()
    import gitlab_mcp.server as s
    s.creds_path = p
    yield s
    gc.reload_client()


@pytest.fixture
def creds(server):
    write_creds(server.creds_path, {"gitlab-larvata": {"url": LARVATA, "token": "t-larvata"},
                                    "gitlab-enzus": {"url": ENZUS, "token": "t-enzus"}})
    return server


@pytest.fixture
def creds_without_enzus(server):
    write_creds(server.creds_path, {"gitlab-larvata": {"url": LARVATA, "token": "t-larvata"}})
    return server


def test_every_tool_accepts_target_id(server):
    tools = server.mcp._tool_manager.list_tools()
    missing = [t.name for t in tools if t.name != "list_targets"
               and "target_id" not in inspect.signature(t.fn).parameters]
    assert missing == []
    assert len(tools) == 31
    assert "list_targets" in {t.name for t in tools}


def test_list_targets_no_token(creds_without_enzus):
    out = creds_without_enzus.list_targets()
    assert "larvata" in out and "credential_state: present" in out and "(預設)" in out
    assert "enzus" in out and "missing" in out
    assert "t-larvata" not in out


def test_tool_routes_target(creds):
    project = {"id": 1, "name": "p", "path_with_namespace": "g/p", "web_url": "u"}
    with patch("requests.Session.request", return_value=ok(project)) as req:
        creds.get_project("g/p", target_id="enzus")
    assert req.call_args.args[1].startswith(ENZUS + "/api/v4/projects/")


def test_tool_unknown_target_returns_error_text(creds):
    with patch("requests.Session.request") as req:
        out = creds.get_project("g/p", target_id="nope")
    assert "可用：larvata, enzus" in out
    req.assert_not_called()


def test_server_info_uses_target_url(creds):
    with patch("requests.Session.request", return_value=ok({"version": "17.0"})):
        out = creds.server_info(target_id="enzus")
    assert ENZUS in out and "17.0" in out


def test_health_check_one_down_other_reported(creds):
    def fake(method, url, **kw):
        if url.startswith(ENZUS):
            raise requests.exceptions.ConnectionError()
        return ok({"version": "17.0"})
    with patch("requests.Session.request", side_effect=fake):
        out = creds.health_check()
    assert "✓ [larvata]" in out and "✗ [enzus]" in out


def test_health_check_reports_missing_token(creds_without_enzus):
    with patch("requests.Session.request", return_value=ok({"version": "17.0"})):
        out = creds_without_enzus.health_check()
    assert "✓ [larvata]" in out and "✗ [enzus]" in out and "t-larvata" not in out


def test_health_check_single_target(creds):
    with patch("requests.Session.request", return_value=ok({"version": "17.0"})):
        out = creds.health_check(target_id="enzus")
    assert "[enzus]" in out and "[larvata]" not in out
