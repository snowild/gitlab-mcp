from unittest.mock import MagicMock, patch

import pytest
import requests

import gitlab_mcp.gitlab_client as gc
from gitlab_mcp.gitlab_client import GitLabAPIError, TargetError, get_client, target_states
from tests.conftest import ENZUS, LARVATA, TWO, write_creds


def ok(data):
    r = MagicMock(status_code=200)
    r.json.return_value = data
    r.raise_for_status.return_value = None
    return r


def http_error(status, body=None):
    r = MagicMock(status_code=status, text=body or "")
    r.json.return_value = {"message": body} if body else {}
    r.raise_for_status.side_effect = requests.exceptions.HTTPError(response=r)
    return r


@pytest.fixture
def creds_path(monkeypatch, tmp_path):
    p = tmp_path / "creds.json"
    monkeypatch.setenv("GITLAB_TARGETS_JSON", TWO)
    monkeypatch.setenv("GITLAB_CREDENTIALS_FILE", str(p))
    gc.reload_client()
    yield p
    gc.reload_client()


@pytest.fixture
def creds(creds_path):
    write_creds(creds_path, {"gitlab-larvata": {"url": LARVATA, "token": "t-larvata"},
                             "gitlab-enzus": {"url": ENZUS, "token": "t-enzus"}})
    return creds_path


@pytest.fixture
def creds_without_enzus(creds_path):
    write_creds(creds_path, {"gitlab-larvata": {"url": LARVATA, "token": "t-larvata"}})
    return creds_path


def test_routes_to_target_base_url_and_token(creds):
    with patch("requests.Session.request", return_value=ok({"version": "17"})) as req:
        client = get_client("enzus")
        client.get_server_version()
    assert req.call_args.args[1] == ENZUS + "/api/v4/version"
    assert client.session.headers["PRIVATE-TOKEN"] == "t-enzus"


def test_default_target_when_none(creds):
    assert get_client(None).target_id == "larvata"


def test_unknown_target_no_request(creds):
    with patch("requests.Session.request") as req, pytest.raises(TargetError, match="larvata, enzus"):
        get_client("nope")
    req.assert_not_called()


def test_missing_token_no_request(creds_without_enzus):
    with patch("requests.Session.request") as req, \
            pytest.raises(TargetError, match=r"^\[enzus\].*gitlab-new\.example\.com"):
        get_client("enzus")
    req.assert_not_called()


def test_ambiguous_and_file_error_raise(creds_path):
    write_creds(creds_path, {"a": {"url": LARVATA, "token": "1"}, "b": {"url": LARVATA, "token": "2"}})
    with pytest.raises(TargetError, match=r"^\[larvata\].*多筆"):
        get_client("larvata")
    write_creds(creds_path, {}, mode=0o644)
    with pytest.raises(TargetError, match=r"^\[larvata\].*chmod 600"):
        get_client("larvata")


def test_target_error_is_gitlab_api_error():
    assert issubclass(TargetError, GitLabAPIError)


def test_token_change_replaces_client(creds_path):
    write_creds(creds_path, {"g": {"url": LARVATA, "token": "old"}})
    a = get_client("larvata")
    write_creds(creds_path, {"g": {"url": LARVATA, "token": "new"}})
    b = get_client("larvata")
    assert b.session.headers["PRIVATE-TOKEN"] == "new" and a is not b
    assert get_client("larvata") is b


def test_http_error_prefixed_and_403_hint(creds):
    with patch("requests.Session.request", return_value=http_error(403)):
        with pytest.raises(GitLabAPIError) as e:
            get_client("enzus").get_server_version()
    assert str(e.value).startswith("[enzus] ") and "未連 VPN" in str(e.value)


def test_connection_error_prefixed(creds):
    with patch("requests.Session.request", side_effect=requests.exceptions.ConnectionError()):
        with pytest.raises(GitLabAPIError, match=r"^\[enzus\] .*gitlab-new"):
            get_client("enzus").get_server_version()


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_token_never_in_error(creds, status):
    with patch("requests.Session.request", return_value=http_error(status, body="x")):
        with pytest.raises(GitLabAPIError) as e:
            get_client("larvata").get_server_version()
    assert "t-larvata" not in str(e.value)


def test_target_states_no_token(creds_without_enzus):
    states = {t.id: c.state for t, c in target_states()}
    assert states == {"larvata": "present", "enzus": "missing"}


def test_legacy_mode_uses_env_token(monkeypatch, tmp_path):
    monkeypatch.setenv("GITLAB_URL", LARVATA)
    monkeypatch.setenv("GITLAB_TOKEN", "t-legacy")
    gc.reload_client()
    client = get_client()
    assert client.target_id == "default"
    assert client.session.headers["PRIVATE-TOKEN"] == "t-legacy"
    assert [(t.id, c.state) for t, c in target_states()] == [("default", "present")]
    gc.reload_client()
