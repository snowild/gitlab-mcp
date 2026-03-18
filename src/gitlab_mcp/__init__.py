"""
GitLab MCP Server
A Model Context Protocol server for managing GitLab resources via Claude Code
"""

try:
    from importlib.metadata import version
    __version__ = version("gitlab-mcp")
except ImportError:
    __version__ = "0.1.0"
