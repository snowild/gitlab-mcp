import json
import logging

import pytest

from gitlab_mcp.config import GitLabConfig
from gitlab_mcp.targets import load_targets, normalize_origin, parse_targets
from tests.conftest import ENZUS, LARVATA, TWO


def test_parse_two_targets():
    ts = parse_targets(TWO)
    assert [(t.id, t.url, t.is_default) for t in ts] == [
        ("larvata", LARVATA, True), ("enzus", ENZUS, False)]


def test_single_target_default_implied():
    assert parse_targets(json.dumps([{"id": "a", "url": LARVATA}]))[0].is_default


def test_normalize_origin_keeps_port_and_lowercases():
    assert normalize_origin("HTTPS://Codes.Example.io:8443/a/b/") == "https://codes.example.io:8443"


@pytest.mark.parametrize("raw,needle", [
    ('[{"id":"a","url":"http://x.io","default":true}]', "https"),
    ('[{"id":"-a","url":"https://x.io","default":true}]', "id"),
    ('[{"id":"a","url":"https://x.io","default":true},{"id":"a","url":"https://y.io"}]', "重複"),
    ('[{"id":"a","url":"https://x.io"},{"id":"b","url":"https://y.io"}]', "default"),
    ('[{"id":"a","url":"https://x.io","default":true},{"id":"b","url":"https://y.io","default":true}]', "default"),
])
def test_parse_rejects(raw, needle):
    with pytest.raises(ValueError, match=needle):
        parse_targets(raw)


@pytest.mark.parametrize("raw", ["not json", "[]", "{}"])
def test_targets_json_invalid(raw):
    with pytest.raises(ValueError, match="GITLAB_TARGETS_JSON"):
        parse_targets(raw)


def test_legacy_mode():
    ts = load_targets({"GITLAB_URL": LARVATA, "GITLAB_TOKEN": "glpat-SECRET"})
    assert [(t.id, t.url, t.is_default) for t in ts] == [("default", LARVATA, True)]
    assert ts[0].legacy_token == "glpat-SECRET"
    assert "glpat-SECRET" not in repr(ts[0])


def test_legacy_allows_http():
    assert load_targets({"GITLAB_URL": "http://gl.local/", "GITLAB_TOKEN": "x"})[0].url == "http://gl.local"


def test_legacy_missing_url():
    with pytest.raises(ValueError, match="GITLAB_URL"):
        load_targets({"GITLAB_TOKEN": "x"})


def test_legacy_missing_token():
    with pytest.raises(ValueError, match="GITLAB_TOKEN"):
        load_targets({"GITLAB_URL": LARVATA})


def test_multi_wins_over_legacy_and_warns(caplog):
    with caplog.at_level(logging.WARNING):
        ts = load_targets({"GITLAB_TARGETS_JSON": TWO, "GITLAB_TOKEN": "glpat-SECRET"})
    assert [t.id for t in ts] == ["larvata", "enzus"]
    assert all(t.legacy_token is None for t in ts)
    assert "GITLAB_TOKEN" in caplog.text and "glpat-SECRET" not in caplog.text


def test_config_multi_target_does_not_require_gitlab_url(monkeypatch):
    monkeypatch.setenv("GITLAB_TARGETS_JSON", TWO)
    monkeypatch.setenv("GITLAB_CREDENTIALS_FILE", "/creds.json")
    c = GitLabConfig()
    assert c.multi_target and c.credentials_file == "/creds.json" and len(c.targets) == 2
    assert "larvata" in repr(c)


def test_config_legacy_repr_hides_token(monkeypatch):
    monkeypatch.setenv("GITLAB_URL", LARVATA)
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-SECRET")
    c = GitLabConfig()
    assert not c.multi_target and "glpat-SECRET" not in repr(c)


def test_legacy_keeps_subpath():
    ts = load_targets({"GITLAB_URL": "https://example.com/gitlab/", "GITLAB_TOKEN": "x"})
    assert ts[0].url == "https://example.com/gitlab"


@pytest.mark.parametrize("url", ["https://u:SECRET@gl.io", "https://gl.io/?private_token=SECRET", "https://gl.io/#SECRET"])
def test_legacy_rejects_userinfo_query_fragment(url):
    with pytest.raises(ValueError) as e:
        load_targets({"GITLAB_URL": url, "GITLAB_TOKEN": "x"})
    assert "SECRET" not in str(e.value)
