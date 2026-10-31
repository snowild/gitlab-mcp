import json
import os

import pytest

LARVATA = "https://gitlab.example.com"
ENZUS = "https://gitlab-new.example.com"
TWO = json.dumps([
    {"id": "larvata", "url": LARVATA + "/", "default": True},
    {"id": "enzus", "url": ENZUS},
])


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """不讀 repo 的 .env（含真 token），也不吃 host 的 GITLAB_* 環境變數。"""
    for k in list(os.environ):
        if k.startswith("GITLAB_"):
            monkeypatch.delenv(k)
    monkeypatch.chdir(tmp_path)
    import gitlab_mcp.config as config
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    config._config = None
    yield
    config._config = None


def write_creds(path, data, mode=0o600):
    path.write_text(json.dumps(data))
    os.chmod(path, mode)
    return str(path)
