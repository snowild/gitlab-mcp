"""
GitLab target 清單
多 target 模式讀 GITLAB_TARGETS_JSON；沒設時退回 GITLAB_URL／GITLAB_TOKEN 單台相容模式
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Mapping, Optional
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
LEGACY_ID = "default"


@dataclass(frozen=True)
class Target:
    id: str
    url: str
    is_default: bool
    legacy_token: Optional[str] = field(default=None, repr=False)


def normalize_origin(url: str) -> str:
    """回傳 scheme://host[:port]（小寫、無 path、無尾斜線）"""
    parts = urlsplit(str(url).strip())
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise ValueError(f"url 必須是 https 且有 host：{url}")
    origin = f"{parts.scheme.lower()}://{parts.hostname.lower()}"
    if parts.port:
        origin += f":{parts.port}"
    return origin


def parse_targets(raw: str) -> list[Target]:
    try:
        items = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("GITLAB_TARGETS_JSON 不是合法的 JSON")
    if not isinstance(items, list) or not items:
        raise ValueError("GITLAB_TARGETS_JSON 必須是非空陣列")

    targets: list[Target] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"GITLAB_TARGETS_JSON 第 {i} 筆不是 object")
        tid = item.get("id")
        if not isinstance(tid, str) or not _ID_RE.match(tid):
            raise ValueError(f"GITLAB_TARGETS_JSON 第 {i} 筆 id 不合法：{tid!r}")
        if any(t.id == tid for t in targets):
            raise ValueError(f"GITLAB_TARGETS_JSON id 重複：{tid}")
        try:
            url = normalize_origin(item.get("url", ""))
        except ValueError as e:
            raise ValueError(f"GITLAB_TARGETS_JSON target {tid}：{e}")
        targets.append(Target(tid, url, item.get("default") is True))

    defaults = sum(t.is_default for t in targets)
    if len(targets) == 1 and defaults == 0:
        targets[0] = Target(targets[0].id, targets[0].url, True)
    elif defaults != 1:
        raise ValueError(f"GITLAB_TARGETS_JSON 必須恰好一台 default: true（目前 {defaults} 台）")
    return targets


def load_targets(env: Mapping[str, str]) -> list[Target]:
    raw = env.get("GITLAB_TARGETS_JSON")
    if raw:
        if env.get("GITLAB_TOKEN"):
            logger.warning("已設定 GITLAB_TARGETS_JSON，GITLAB_TOKEN 被忽略（token 改從憑證檔讀）")
        return parse_targets(raw)

    url = env.get("GITLAB_URL")
    token = env.get("GITLAB_TOKEN")
    if not url:
        raise ValueError("必要的環境變數 GITLAB_URL 未設定（或改用 GITLAB_TARGETS_JSON）")
    if not token or not token.strip():
        raise ValueError("必要的環境變數 GITLAB_TOKEN 未設定（或改用 GITLAB_TARGETS_JSON）")
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("GITLAB_URL 必須以 http:// 或 https:// 開頭且有 host")
    if parts.username or parts.password or parts.query or parts.fragment:
        # 網址會出現在 tool 回傳與錯誤訊息，不可夾帶帳密或 token
        raise ValueError("GITLAB_URL 不可包含帳號密碼、query 或 fragment")
    # 相容模式保留 path（GitLab 可能裝在子路徑），行為同舊版
    return [Target(LEGACY_ID, url.strip().rstrip("/"), True, legacy_token=token)]
