"""
配置管理模組
負責載入和驗證環境變數配置
"""

import os
from typing import Optional
from dotenv import load_dotenv


class GitLabConfig:
    """GitLab MCP 服務器配置管理"""

    def __init__(self):
        load_dotenv()

        # 必要配置
        self.gitlab_url = self._get_required_env("GITLAB_URL")
        self.gitlab_token = self._get_required_env("GITLAB_TOKEN")

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

    def _get_required_env(self, key: str) -> str:
        """取得必要的環境變數，如果不存在則拋出錯誤"""
        value = os.getenv(key)
        if not value:
            raise ValueError(f"必要的環境變數 {key} 未設定")
        return value

    def _validate_config(self) -> None:
        """驗證配置的有效性"""
        # 驗證 URL 格式
        if not self.gitlab_url.startswith(('http://', 'https://')):
            raise ValueError("GITLAB_URL 必須以 http:// 或 https:// 開頭")

        # 移除末尾的斜線
        self.gitlab_url = self.gitlab_url.rstrip('/')

        # 驗證 token 不為空
        if not self.gitlab_token.strip():
            raise ValueError("GITLAB_TOKEN 不能為空")

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
    def api_base_url(self) -> str:
        """回傳 GitLab API v4 的基礎 URL"""
        return f"{self.gitlab_url}/api/v4"

    @property
    def api_headers(self) -> dict[str, str]:
        """回傳 API 請求所需的標頭"""
        return {
            "PRIVATE-TOKEN": self.gitlab_token,
            "Content-Type": "application/json",
        }

    def __repr__(self) -> str:
        """除錯用的字串表示，隱藏敏感資訊"""
        return (
            f"GitLabConfig(url='{self.gitlab_url}', timeout={self.timeout}, "
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
