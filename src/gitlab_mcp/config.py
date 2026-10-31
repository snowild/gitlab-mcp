"""
配置管理模組
負責載入和驗證環境變數配置
"""

import os
from typing import Optional
from dotenv import load_dotenv

from .targets import Target, load_targets


class GitLabConfig:
    """GitLab MCP 服務器配置管理"""

    def __init__(self):
        load_dotenv()

        # GitLab target 清單（多 target 或 GITLAB_URL/GITLAB_TOKEN 相容模式）
        self.multi_target = bool(os.getenv("GITLAB_TARGETS_JSON"))
        self.targets: list[Target] = load_targets(os.environ)
        self.credentials_file: Optional[str] = os.getenv("GITLAB_CREDENTIALS_FILE")

        # 可選配置
        self.timeout = int(os.getenv("GITLAB_TIMEOUT", "30"))

        # SSE 傳輸配置
        self.transport = os.getenv("GITLAB_MCP_TRANSPORT", "stdio").lower()
        self.sse_host = os.getenv("GITLAB_MCP_HOST", "0.0.0.0")
        self.sse_port = int(os.getenv("GITLAB_MCP_PORT", "8000"))

        # 日誌級別
        self.log_level = os.getenv("GITLAB_MCP_LOG_LEVEL", "INFO").upper()
        os.environ["FASTMCP_LOG_LEVEL"] = self.log_level
        self.debug_mode = self.log_level == "DEBUG"

        self._validate_config()

    def _validate_config(self) -> None:
        """驗證配置的有效性"""
        if self.multi_target and not self.credentials_file:
            raise ValueError("多 target 模式必須設定 GITLAB_CREDENTIALS_FILE")

        # 驗證 timeout 值
        if self.timeout <= 0:
            raise ValueError("GITLAB_TIMEOUT 必須大於 0")

        # 驗證 log_level 值
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if self.log_level not in valid_levels:
            raise ValueError(f"日誌級別必須是以下值之一: {', '.join(valid_levels)}（當前: {self.log_level}）")

        # 驗證 transport 值
        valid_transports = ['stdio', 'sse']
        if self.transport not in valid_transports:
            raise ValueError(f"傳輸模式必須是以下值之一: {', '.join(valid_transports)}（當前: {self.transport}）")

        # 驗證 SSE port 值
        if self.sse_port <= 0 or self.sse_port > 65535:
            raise ValueError(f"SSE 埠號必須在 1-65535 之間（當前: {self.sse_port}）")

    @property
    def default_target(self) -> Target:
        return next(t for t in self.targets if t.is_default)

    def __repr__(self) -> str:
        """除錯用的字串表示，不含 token"""
        targets = ", ".join(f"{t.id}={t.url}" for t in self.targets)
        return (
            f"GitLabConfig(targets=[{targets}], timeout={self.timeout}, "
            f"transport='{self.transport}', sse_host='{self.sse_host}', "
            f"sse_port={self.sse_port}, log_level='{self.log_level}', "
            f"debug={self.debug_mode})"
        )


# 全域配置實例
_config: Optional[GitLabConfig] = None


def get_config() -> GitLabConfig:
    """取得全域配置實例（單例模式）"""
    global _config
    if _config is None:
        _config = GitLabConfig()
    return _config


def reload_config() -> GitLabConfig:
    """重新載入配置（主要用於測試）"""
    global _config
    _config = None
    return get_config()
