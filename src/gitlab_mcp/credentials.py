"""
個人憑證檔（~/.larvata/credentials.json）查找
格式：{"<任意名稱>": {"url": "...", "token": "..."}}，以 url 的 origin 對應 target
錯誤訊息只含路徑與修法，不含檔案內容
"""

import json
import os
import stat
from dataclasses import dataclass, field
from typing import Literal, Optional

from .targets import Target, normalize_origin

State = Literal["present", "missing", "ambiguous", "file_error"]


@dataclass(frozen=True)
class Credential:
    state: State
    token: Optional[str] = field(default=None, repr=False)
    error: Optional[str] = None


def _read_file(path: str) -> dict:
    """回傳 JSON object；有問題時拋 ValueError（訊息含修法）"""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise ValueError(f"憑證檔 {path} 不存在，請依 setup 2.0 建立")
    except OSError:
        raise ValueError(f"憑證檔 {path} 無法存取，請確認路徑與上層目錄權限")
    if not stat.S_ISREG(st.st_mode):
        raise ValueError(f"憑證檔 {path} 不是一般檔案，請確認 docker -v 的來源是檔案而不是目錄")
    if st.st_mode & 0o077:
        raise ValueError(f"憑證檔 {path} 權限過寬，請在 host 執行 chmod 600 ~/.larvata/credentials.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        raise ValueError(f"憑證檔 {path} 無法讀取或不是合法 JSON，請檢查 JSON 格式")
    if not isinstance(data, dict):
        raise ValueError(f"憑證檔 {path} 必須是 JSON object，請檢查 JSON 格式")
    return data


def lookup_credentials(path: str, targets: list[Target]) -> dict[str, Credential]:
    try:
        data = _read_file(path)
    except ValueError as e:
        return {t.id: Credential("file_error", error=str(e)) for t in targets}

    tokens_by_origin: dict[str, list[str]] = {}
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        token = entry.get("token")
        if not isinstance(token, str) or not token.strip():
            continue
        token = token.strip()
        if any(ord(c) < 0x20 or ord(c) == 0x7f for c in token):
            continue  # header 放不進去，requests 會在例外訊息裡帶出值
        try:
            origin = normalize_origin(entry.get("url", ""))
        except ValueError:
            continue
        tokens_by_origin.setdefault(origin, []).append(token)

    result: dict[str, Credential] = {}
    for t in targets:
        found = tokens_by_origin.get(t.url, [])
        if len(found) == 1:
            result[t.id] = Credential("present", found[0])
        elif found:
            result[t.id] = Credential("ambiguous")
        else:
            result[t.id] = Credential("missing")
    return result
