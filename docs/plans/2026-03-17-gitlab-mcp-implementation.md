# GitLab MCP Server Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python MCP server that connects to self-hosted GitLab (v14.10.5) via REST API v4, supporting 30 tools for Projects, Merge Requests, CI/CD Pipelines, and Repository operations.

**Architecture:** FastMCP-based server following redmine-mcp patterns — singleton config, requests-based API client with unified error handling, `@mcp.tool()` decorated functions returning formatted strings. SSE transport for Docker deployment.

**Tech Stack:** Python 3.12+, FastMCP (mcp[cli]>=1.9.4), requests, python-dotenv, uv package manager, Docker multi-stage build.

---

### Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/gitlab_mcp/__init__.py`
- Create: `.env.example`
- Create: `Dockerfile`
- Create: `docker-compose.yml`

**Step 1: Create pyproject.toml**

```python
# pyproject.toml — 參考 redmine-mcp/pyproject.toml 格式
# name: gitlab-mcp
# version: 0.1.0
# requires-python: >=3.12
# dependencies: mcp[cli]>=1.9.4, requests>=2.31.0, python-dotenv>=1.0.0
# build-system: hatchling
# script entry: gitlab-mcp = "gitlab_mcp.server:main"
```

**Step 2: Create src/gitlab_mcp/__init__.py**

```python
"""
GitLab MCP Server
A Model Context Protocol server for managing GitLab resources via Claude Code
"""
try:
    from importlib.metadata import version
    __version__ = version("gitlab-mcp")
except ImportError:
    __version__ = "0.1.0"
```

**Step 3: Create .env.example**

```bash
# GITLAB_URL=https://your-gitlab.example.com
# GITLAB_TOKEN=your_personal_access_token
# GITLAB_MCP_TRANSPORT=sse
# GITLAB_MCP_HOST=0.0.0.0
# GITLAB_MCP_PORT=8000
# GITLAB_MCP_LOG_LEVEL=INFO
# GITLAB_TIMEOUT=30
```

**Step 4: Create Dockerfile**

Multi-stage build following redmine-mcp pattern:
- Stage 1 (builder): python:3.12-slim + uv, copy source, `uv sync --frozen --no-dev`
- Stage 2 (runtime): python:3.12-slim, install curl, create mcp user, copy .venv + src
- ENV: PATH, PYTHONUNBUFFERED, GITLAB_MCP_TRANSPORT=sse
- HEALTHCHECK: `curl -sf http://localhost:8000/sse`
- CMD: `python -m gitlab_mcp.server --transport sse`

**Step 5: Create docker-compose.yml**

```yaml
# services.gitlab-mcp: build ., ports 8000:8000
# environment: GITLAB_URL, GITLAB_TOKEN from .env
# restart: unless-stopped, healthcheck
```

**Step 6: Initialize uv project**

Run: `cd /Users/jacktsai/workspace/mcp-project/gitlab-mcp && uv sync`
Expected: Creates uv.lock, .venv directory

---

### Task 2: Configuration Module

**Files:**
- Create: `src/gitlab_mcp/config.py`

**Step 1: Implement GitLabConfig class**

Follow redmine-mcp/src/redmine_mcp/config.py pattern exactly:
- `__init__`: load_dotenv, read GITLAB_URL (required), GITLAB_TOKEN (required)
- Optional: GITLAB_MCP_TRANSPORT, GITLAB_MCP_HOST, GITLAB_MCP_PORT, GITLAB_MCP_LOG_LEVEL, GITLAB_TIMEOUT
- `_get_required_env(key)`: raise ValueError if missing
- `_validate_config()`: URL format (http/https), strip trailing slash, token not empty, timeout > 0, valid log level, valid transport, valid port range
- `api_base_url` property: `f"{self.gitlab_url}/api/v4"`
- `api_headers` property: `{"PRIVATE-TOKEN": self.gitlab_token, "Content-Type": "application/json"}`
- Set `os.environ["FASTMCP_LOG_LEVEL"]` before FastMCP init
- Singleton: `_config`, `get_config()`, `reload_config()`

**Step 2: Verify config loads**

Run: `cd /Users/jacktsai/workspace/mcp-project/gitlab-mcp && GITLAB_URL=https://test.example.com GITLAB_TOKEN=test uv run python -c "from gitlab_mcp.config import get_config; c = get_config(); print(c)"`
Expected: Prints config repr without error

---

### Task 3: GitLab API Client — Core Infrastructure

**Files:**
- Create: `src/gitlab_mcp/gitlab_client.py`

**Step 1: Implement core classes and HTTP layer**

```python
# GitLabAPIError(Exception) — status_code, response_data
#
# GitLabClient:
#   __init__(config): session with headers, timeout
#   _make_request(method, endpoint, **kwargs) -> requests.Response
#     - Build full URL: config.api_base_url + endpoint
#     - Unified error handling: Timeout, ConnectionError, HTTPError -> GitLabAPIError
#     - For JSON responses: return response.json()
#     - For text responses (job logs): return response.text
#   _get_paginated(endpoint, params, max_pages) -> list
#     - Handle X-Next-Page header for pagination
#     - Return accumulated results
#   _encode_path(path: str) -> str
#     - URL-encode project paths (e.g., "group/project" -> "group%2Fproject")
#   _resolve_project_id(project_id: int | str) -> str
#     - If int or numeric string: return as-is
#     - If path string: URL-encode it
#
# Singleton: _client, get_client(), reload_client()
```

**Step 2: Implement Projects API methods**

```python
# list_projects(search, membership, page, per_page) -> list[dict]
#   GET /projects?search=&membership=true&page=&per_page=
#
# get_project(project_id) -> dict
#   GET /projects/:id
#
# list_project_members(project_id, page, per_page) -> list[dict]
#   GET /projects/:id/members
```

**Step 3: Implement Merge Requests API methods**

```python
# list_merge_requests(project_id, state, page, per_page) -> list[dict]
#   GET /projects/:id/merge_requests?state=&page=&per_page=
#
# get_merge_request(project_id, mr_iid) -> dict
#   GET /projects/:id/merge_requests/:iid
#
# create_merge_request(project_id, source_branch, target_branch, title, **kwargs) -> dict
#   POST /projects/:id/merge_requests
#   Body: {source_branch, target_branch, title, description, assignee_id, reviewer_ids}
#
# update_merge_request(project_id, mr_iid, **kwargs) -> dict
#   PUT /projects/:id/merge_requests/:iid
#   Body: {title, description, state_event, assignee_id, reviewer_ids}
#
# merge_merge_request(project_id, mr_iid, merge_commit_message, should_remove_source_branch) -> dict
#   PUT /projects/:id/merge_requests/:iid/merge
#
# approve_merge_request(project_id, mr_iid) -> dict
#   POST /projects/:id/merge_requests/:iid/approve
#
# get_merge_request_changes(project_id, mr_iid) -> dict
#   GET /projects/:id/merge_requests/:iid/changes
#
# get_merge_request_commits(project_id, mr_iid) -> list[dict]
#   GET /projects/:id/merge_requests/:iid/commits
#
# list_merge_request_notes(project_id, mr_iid, sort, page, per_page) -> list[dict]
#   GET /projects/:id/merge_requests/:iid/notes?sort=&page=&per_page=
#
# create_merge_request_note(project_id, mr_iid, body) -> dict
#   POST /projects/:id/merge_requests/:iid/notes
```

**Step 4: Implement Pipelines & Jobs API methods**

```python
# list_pipelines(project_id, status, ref, page, per_page) -> list[dict]
#   GET /projects/:id/pipelines?status=&ref=&page=&per_page=
#
# get_pipeline(project_id, pipeline_id) -> dict
#   GET /projects/:id/pipelines/:pipeline_id
#
# create_pipeline(project_id, ref, variables) -> dict
#   POST /projects/:id/pipeline  Body: {ref, variables: [{key, value}]}
#
# retry_pipeline(project_id, pipeline_id) -> dict
#   POST /projects/:id/pipelines/:pipeline_id/retry
#
# cancel_pipeline(project_id, pipeline_id) -> dict
#   POST /projects/:id/pipelines/:pipeline_id/cancel
#
# list_pipeline_jobs(project_id, pipeline_id, page, per_page) -> list[dict]
#   GET /projects/:id/pipelines/:pipeline_id/jobs
#
# get_job(project_id, job_id) -> dict
#   GET /projects/:id/jobs/:job_id
#
# get_job_log(project_id, job_id) -> str
#   GET /projects/:id/jobs/:job_id/trace  (Accept: text/plain)
#
# retry_job(project_id, job_id) -> dict
#   POST /projects/:id/jobs/:job_id/retry
```

**Step 5: Implement Repository API methods**

```python
# list_branches(project_id, search, page, per_page) -> list[dict]
#   GET /projects/:id/repository/branches?search=&page=&per_page=
#
# get_branch(project_id, branch_name) -> dict
#   GET /projects/:id/repository/branches/:branch (URL-encode branch_name)
#
# list_commits(project_id, ref_name, path, page, per_page) -> list[dict]
#   GET /projects/:id/repository/commits?ref_name=&path=&page=&per_page=
#
# get_commit(project_id, sha) -> dict
#   GET /projects/:id/repository/commits/:sha
#
# compare_branches(project_id, from_ref, to_ref) -> dict
#   GET /projects/:id/repository/compare?from=&to=
#
# list_repository_tree(project_id, path, ref, recursive, page, per_page) -> list[dict]
#   GET /projects/:id/repository/tree?path=&ref=&recursive=&page=&per_page=
```

**Step 6: Implement server info helpers**

```python
# get_server_version() -> dict
#   GET /version
#
# test_connection() -> bool
#   Try GET /version, return True/False
```

---

### Task 4: Input Validators

**Files:**
- Create: `src/gitlab_mcp/validators.py`

**Step 1: Implement GitLabValidator**

```python
# ValidationResult(is_valid, errors, warnings) — dataclass
#
# GitLabValidator:
#   Constants:
#     MAX_TITLE_LENGTH = 255
#     MAX_DESCRIPTION_LENGTH = 1_048_576
#     VALID_MR_STATES = {"opened", "closed", "merged", "all"}
#     VALID_PIPELINE_STATUSES = {"running", "pending", "success", "failed", "canceled", "skipped"}
#     VALID_MR_STATE_EVENTS = {"close", "reopen"}
#     VALID_PIPELINE_SORT = {"id_desc", "id_asc", "ref_desc", "ref_asc", ...}
#
#   Methods:
#     validate_project_id(project_id) -> ValidationResult
#       - Accept int or str (numeric or path format like "group/project")
#
#     validate_merge_request_data(data, is_update) -> ValidationResult
#       - Required for create: source_branch, target_branch, title
#       - Title length <= 255
#       - state_event in VALID_MR_STATE_EVENTS (if provided)
#
#     validate_pipeline_data(data) -> ValidationResult
#       - Required: ref
#       - Variables must be list of {key, value} dicts
#
#     get_friendly_error_message(error, context) -> str
#       - Map HTTP status codes to user-friendly messages
#       - Handle ConnectionError, Timeout, etc.
```

---

### Task 5: MCP Server — All 30 Tools

**Files:**
- Create: `src/gitlab_mcp/server.py`

**Step 1: Server setup and admin tools (2 tools)**

```python
# Import pattern (same as redmine-mcp):
#   from .config import get_config
#   config = get_config()  # BEFORE FastMCP import
#   from mcp.server.fastmcp import FastMCP
#   from .gitlab_client import get_client, GitLabAPIError
#
# mcp = FastMCP("GitLab MCP")
#
# @mcp.tool() server_info() -> str
# @mcp.tool() health_check() -> str
```

**Step 2: Projects tools (3 tools)**

```python
# @mcp.tool() list_projects(search, page, per_page) -> str
#   - Format: table-like output with id, name, path_with_namespace, web_url
#
# @mcp.tool() get_project(project_id) -> str
#   - Format: detailed project info
#
# @mcp.tool() list_project_members(project_id, page, per_page) -> str
#   - Format: member list with name, username, access_level
```

**Step 3: Merge Requests tools (10 tools)**

```python
# @mcp.tool() list_merge_requests(project_id, state, page, per_page) -> str
# @mcp.tool() get_merge_request(project_id, mr_iid) -> str
# @mcp.tool() create_merge_request(project_id, source_branch, target_branch, title, description, assignee_id, reviewer_ids) -> str
# @mcp.tool() update_merge_request(project_id, mr_iid, title, description, state_event, assignee_id, reviewer_ids) -> str
# @mcp.tool() merge_merge_request(project_id, mr_iid, merge_commit_message, should_remove_source_branch) -> str
# @mcp.tool() approve_merge_request(project_id, mr_iid) -> str
# @mcp.tool() get_merge_request_changes(project_id, mr_iid) -> str
# @mcp.tool() get_merge_request_commits(project_id, mr_iid) -> str
# @mcp.tool() list_merge_request_notes(project_id, mr_iid, page, per_page) -> str
# @mcp.tool() create_merge_request_note(project_id, mr_iid, body) -> str
#
# Each tool:
#   1. Validate input with GitLabValidator
#   2. Call client method
#   3. Format output as readable text
#   4. Catch GitLabAPIError -> friendly message
```

**Step 4: CI/CD Pipelines & Jobs tools (9 tools)**

```python
# @mcp.tool() list_pipelines(project_id, status, ref, page, per_page) -> str
# @mcp.tool() get_pipeline(project_id, pipeline_id) -> str
# @mcp.tool() create_pipeline(project_id, ref, variables) -> str
# @mcp.tool() retry_pipeline(project_id, pipeline_id) -> str
# @mcp.tool() cancel_pipeline(project_id, pipeline_id) -> str
# @mcp.tool() list_pipeline_jobs(project_id, pipeline_id, page, per_page) -> str
# @mcp.tool() get_job(project_id, job_id) -> str
# @mcp.tool() get_job_log(project_id, job_id, last_lines) -> str
#   - last_lines: optional, return only last N lines of log (logs can be huge)
# @mcp.tool() retry_job(project_id, job_id) -> str
```

**Step 5: Repository tools (6 tools)**

```python
# @mcp.tool() list_branches(project_id, search, page, per_page) -> str
# @mcp.tool() get_branch(project_id, branch_name) -> str
# @mcp.tool() list_commits(project_id, ref_name, path, page, per_page) -> str
# @mcp.tool() get_commit(project_id, sha) -> str
# @mcp.tool() compare_branches(project_id, from_ref, to_ref) -> str
# @mcp.tool() list_repository_tree(project_id, path, ref, recursive) -> str
```

**Step 6: main() entry point**

```python
# def main():
#   argparse: --transport (stdio/sse), --host, --port
#   CLI args override env vars
#   if sse: set mcp.settings.host/port, print startup msg, mcp.run('sse')
#   else: mcp.run('stdio')
#
# if __name__ == "__main__": main()
```

**Step 7: Verify server starts**

Run: `cd /Users/jacktsai/workspace/mcp-project/gitlab-mcp && GITLAB_URL=https://test.example.com GITLAB_TOKEN=test uv run python -m gitlab_mcp.server --transport sse --port 8001 &`
Expected: Prints "啟動 SSE 模式: http://0.0.0.0:8001", server starts
Then: `curl -sf http://localhost:8001/sse` should connect
Cleanup: Kill the background process

---

### Task 6: Docker Build & Verification

**Files:**
- Verify: `Dockerfile`
- Verify: `docker-compose.yml`

**Step 1: Build Docker image**

Run: `cd /Users/jacktsai/workspace/mcp-project/gitlab-mcp && docker compose build`
Expected: Successful build with no errors

**Step 2: Test Docker container**

Run: Create .env with test values, `docker compose up -d`, check logs
Expected: Container starts, health check passes

---

## Task Dependencies

```
Task 1 (Scaffold)
    → Task 2 (Config)
        → Task 3 (Client) + Task 4 (Validators) [parallel]
            → Task 5 (Server)
                → Task 6 (Docker)
```

## Notes

- **No auto-commit**: 等待使用者測試通過後才 commit
- **GitLab 14.10.5 相容性**: approve API 可能需要 Premium，其他 API 均可用
- **分頁**: 所有 list 類工具預設 per_page=20，最大 100
- **project_id**: 支援數字 ID 和 URL-encoded path（如 `group%2Fproject`）
- **Job log**: 可能非常大，提供 last_lines 參數截取最後 N 行
