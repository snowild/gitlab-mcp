import os

import pytest

from gitlab_mcp.credentials import Credential, lookup_credentials
from gitlab_mcp.targets import Target
from tests.conftest import ENZUS, LARVATA, write_creds

T_LARVATA = Target("larvata", LARVATA, True)
T_ENZUS = Target("enzus", ENZUS, False)


def test_present_by_origin_any_key(tmp_path):
    f = write_creds(tmp_path / "c.json", {
        "gitlab-enzus": {"url": ENZUS, "token": "t-enzus"},
        "larvata": {"url": "https://projects.larvata.tw", "token": "r"},
    })
    r = lookup_credentials(f, [T_LARVATA, T_ENZUS])
    assert r["enzus"].state == "present" and r["enzus"].token == "t-enzus"
    assert r["larvata"].state == "missing" and r["larvata"].token is None


def test_origin_ignores_trailing_slash_and_path(tmp_path):
    f = write_creds(tmp_path / "c.json", {"x": {"url": LARVATA + "/some/path/", "token": "t"}})
    assert lookup_credentials(f, [T_LARVATA])["larvata"].state == "present"


def test_empty_token_is_missing(tmp_path):
    f = write_creds(tmp_path / "c.json", {"gitlab-larvata": {"url": LARVATA, "token": ""}})
    assert lookup_credentials(f, [T_LARVATA])["larvata"].state == "missing"


def test_ambiguous(tmp_path):
    f = write_creds(tmp_path / "c.json", {
        "a": {"url": LARVATA, "token": "t1"}, "b": {"url": LARVATA + "/", "token": "t2"}})
    r = lookup_credentials(f, [T_LARVATA])["larvata"]
    assert r.state == "ambiguous" and r.token is None


def test_malformed_entry_is_skipped(tmp_path):
    f = write_creds(tmp_path / "c.json", {
        "a": "str", "b": {"token": "t"}, "c": {"url": "http://x", "token": "t"},
        "d": {"url": LARVATA, "token": 123}, "e": {"url": LARVATA, "token": "ok"}})
    r = lookup_credentials(f, [T_LARVATA])["larvata"]
    assert r.state == "present" and r.token == "ok"


@pytest.mark.parametrize("case", ["missing_file", "directory", "mode_644", "bad_json", "json_list"])
def test_file_error(tmp_path, case):
    p = tmp_path / "c.json"
    if case == "directory":
        p.mkdir()
    elif case == "mode_644":
        write_creds(p, {"g": {"url": LARVATA, "token": "SECRET"}}, mode=0o644)
    elif case == "bad_json":
        p.write_text('{"g": {"url": "x", "token": "SECRET"')
        os.chmod(p, 0o600)
    elif case == "json_list":
        write_creds(p, [{"url": LARVATA, "token": "SECRET"}])
    path = str(p)
    r = lookup_credentials(path, [T_LARVATA, T_ENZUS])
    assert {c.state for c in r.values()} == {"file_error"}
    assert path in r["larvata"].error and "SECRET" not in r["larvata"].error
    assert all(c.token is None for c in r.values())


def test_repr_hides_token():
    assert "t-x" not in repr(Credential("present", "t-x"))
