# GitLab MCP Server 設計文件

> 建立日期：2026-03-17
> 狀態：已確認，準備實作

## 1. 概述

### 目標

建立一個 Python MCP Server，透過 GitLab REST API v4 連接自架 GitLab（v14.10.5），
讓 AI 助手（Claude Code、Cursor 等）能直接操作 GitLab 資源。

### 約束條件

- GitLab 版本：14.10.5（無法使用官方 MCP endpoint，需 ≥18.6）
- 認證方式：Personal Access Token (PAT)
- 傳輸協議：SSE（Server-Sent Events）為主，同時支援 stdio
- 部署方式：Docker Container
- 開發語言：Python 3.12+
- 參考架構：redmine-mcp（同目錄下的既有專案）

## 2. 專案結構

```
gitlab-mcp/
├── src/gitlab_mcp/
│   ├── __init__.py              # 套件初始化，版本資訊
│   ├── config.py                # 配置管理（單例模式）
│   ├── gitlab_client.py         # GitLab REST API v4 客戶端
│   ├── server.py                # FastMCP server + tool 註冊
│   └── validators.py            # 輸入驗證
├── tests/
│   ├── unit/
│   └── integration/
├── docs/
│   └── plans/
├── pyproject.toml               # 專案依賴與建置配置
├── Dockerfile                   # 多階段 Docker 建置
├── docker-compose.yml           # 容器編排
├── .env.example                 # 環境變數範例
└── README.md
```

## 3. 配置設計

### 環境變數

| 變數 | 必填 | 預設值 | 說明 |
|------|------|--------|------|
| `GITLAB_URL` | Yes | — | GitLab 位址，如 `https://gitlab.example.com` |
| `GITLAB_TOKEN` | Yes | — | Personal Access Token |
| `GITLAB_MCP_TRANSPORT` | No | `stdio` | 傳輸模式：`stdio` 或 `sse` |
| `GITLAB_MCP_HOST` | No | `0.0.0.0` | SSE 監聽位址 |
| `GITLAB_MCP_PORT` | No | `8000` | SSE 監聽端口 |
| `GITLAB_MCP_LOG_LEVEL` | No | `INFO` | 日誌等級 |
| `GITLAB_TIMEOUT` | No | `30` | API 請求逾時（秒） |

### 配置模組 (`config.py`)

```python
@dataclass
class GitLabConfig:
    gitlab_url: str              # GitLab 伺服器 URL（移除尾端斜線）
    gitlab_token: str            # Personal Access Token
    transport: str = "stdio"     # stdio / sse
    sse_host: str = "0.0.0.0"
    sse_port: int = 8000
    log_level: str = "INFO"
    timeout: int = 30

    @property
    def api_base_url(self) -> str:
        return f"{self.gitlab_url}/api/v4"

    @property
    def api_headers(self) -> dict:
        return {
            "PRIVATE-TOKEN": self.gitlab_token,
            "Content-Type": "application/json",
        }
```

- 使用單例模式（`get_config()`）
- 啟動時驗證必填欄位，缺失則拋出明確錯誤

## 4. API 客戶端設計 (`gitlab_client.py`)

### 核心類別

```python
class GitLabAPIError(Exception):
    """GitLab API 錯誤"""
    def __init__(self, message: str, status_code: int = None, response_data: dict = None):
        ...

class GitLabClient:
    def __init__(self, config: GitLabConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(config.api_headers)
        self.session.timeout = config.timeout

    def _make_request(self, method: str, endpoint: str, **kwargs) -> dict | list:
        """統一 HTTP 請求處理，含錯誤轉換"""
        ...

    def _get_paginated(self, endpoint: str, **kwargs) -> list:
        """處理 GitLab 分頁 API（X-Page, X-Total-Pages headers）"""
        ...
```

### 資料類別

```python
@dataclass
class GitLabProject:
    id: int
    name: str
    path_with_namespace: str
    description: str | None
    default_branch: str
    web_url: str
    created_at: str
    last_activity_at: str

@dataclass
class GitLabMergeRequest:
    id: int
    iid: int
    title: str
    description: str | None
    state: str                   # opened, closed, merged
    source_branch: str
    target_branch: str
    author: dict
    assignee: dict | None
    reviewers: list
    web_url: str
    created_at: str
    updated_at: str
    merged_at: str | None
    pipeline: dict | None

@dataclass
class GitLabPipeline:
    id: int
    status: str                  # running, pending, success, failed, canceled, skipped
    ref: str
    sha: str
    web_url: str
    created_at: str
    updated_at: str

@dataclass
class GitLabJob:
    id: int
    name: str
    stage: str
    status: str
    web_url: str
    duration: float | None
    created_at: str
    started_at: str | None
    finished_at: str | None

@dataclass
class GitLabBranch:
    name: str
    merged: bool
    protected: bool
    default: bool
    web_url: str
    commit: dict

@dataclass
class GitLabCommit:
    id: str
    short_id: str
    title: str
    message: str
    author_name: str
    authored_date: str
    web_url: str
```

### API 方法分類

#### Projects
```python
def list_projects(self, search: str = None, page: int = 1, per_page: int = 20) -> list[dict]:
    """GET /projects"""

def get_project(self, project_id: int | str) -> dict:
    """GET /projects/:id — 支援 ID 或 path（URL encoded）"""

def list_project_members(self, project_id: int | str, page: int = 1, per_page: int = 20) -> list[dict]:
    """GET /projects/:id/members"""
```

#### Merge Requests
```python
def list_merge_requests(self, project_id, state: str = None, page: int = 1, per_page: int = 20) -> list[dict]:
    """GET /projects/:id/merge_requests"""

def get_merge_request(self, project_id, mr_iid: int) -> dict:
    """GET /projects/:id/merge_requests/:iid"""

def create_merge_request(self, project_id, source_branch: str, target_branch: str, title: str, **kwargs) -> dict:
    """POST /projects/:id/merge_requests"""

def update_merge_request(self, project_id, mr_iid: int, **kwargs) -> dict:
    """PUT /projects/:id/merge_requests/:iid"""

def merge_merge_request(self, project_id, mr_iid: int, merge_commit_message: str = None, should_remove_source_branch: bool = False) -> dict:
    """PUT /projects/:id/merge_requests/:iid/merge"""

def approve_merge_request(self, project_id, mr_iid: int) -> dict:
    """POST /projects/:id/merge_requests/:iid/approve"""

def get_merge_request_changes(self, project_id, mr_iid: int) -> dict:
    """GET /projects/:id/merge_requests/:iid/changes"""

def get_merge_request_commits(self, project_id, mr_iid: int) -> list[dict]:
    """GET /projects/:id/merge_requests/:iid/commits"""

def list_merge_request_notes(self, project_id, mr_iid: int, page: int = 1, per_page: int = 20) -> list[dict]:
    """GET /projects/:id/merge_requests/:iid/notes"""

def create_merge_request_note(self, project_id, mr_iid: int, body: str) -> dict:
    """POST /projects/:id/merge_requests/:iid/notes"""
```

#### CI/CD Pipelines & Jobs
```python
def list_pipelines(self, project_id, status: str = None, ref: str = None, page: int = 1, per_page: int = 20) -> list[dict]:
    """GET /projects/:id/pipelines"""

def get_pipeline(self, project_id, pipeline_id: int) -> dict:
    """GET /projects/:id/pipelines/:pipeline_id"""

def create_pipeline(self, project_id, ref: str, variables: list[dict] = None) -> dict:
    """POST /projects/:id/pipeline"""

def retry_pipeline(self, project_id, pipeline_id: int) -> dict:
    """POST /projects/:id/pipelines/:pipeline_id/retry"""

def cancel_pipeline(self, project_id, pipeline_id: int) -> dict:
    """POST /projects/:id/pipelines/:pipeline_id/cancel"""

def list_pipeline_jobs(self, project_id, pipeline_id: int, page: int = 1, per_page: int = 20) -> list[dict]:
    """GET /projects/:id/pipelines/:pipeline_id/jobs"""

def get_job(self, project_id, job_id: int) -> dict:
    """GET /projects/:id/jobs/:job_id"""

def get_job_log(self, project_id, job_id: int) -> str:
    """GET /projects/:id/jobs/:job_id/trace — 回傳純文字日誌"""

def retry_job(self, project_id, job_id: int) -> dict:
    """POST /projects/:id/jobs/:job_id/retry"""
```

#### Repository
```python
def list_branches(self, project_id, search: str = None, page: int = 1, per_page: int = 20) -> list[dict]:
    """GET /projects/:id/repository/branches"""

def get_branch(self, project_id, branch_name: str) -> dict:
    """GET /projects/:id/repository/branches/:branch"""

def list_commits(self, project_id, ref_name: str = None, path: str = None, page: int = 1, per_page: int = 20) -> list[dict]:
    """GET /projects/:id/repository/commits"""

def get_commit(self, project_id, sha: str) -> dict:
    """GET /projects/:id/repository/commits/:sha"""

def compare_branches(self, project_id, from_ref: str, to_ref: str) -> dict:
    """GET /projects/:id/repository/compare"""

def list_repository_tree(self, project_id, path: str = "", ref: str = None, recursive: bool = False) -> list[dict]:
    """GET /projects/:id/repository/tree"""
```

## 5. MCP Tool 設計 (`server.py`)

### 工具註冊模式

所有工具使用 `@mcp.tool()` 裝飾器註冊，回傳格式統一為 `str`（JSON 格式化文字）。

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("GitLab MCP")

@mcp.tool()
def list_projects(search: str = None, page: int = 1, per_page: int = 20) -> str:
    """列出可存取的 GitLab 專案。

    Args:
        search: 搜尋關鍵字（專案名稱）
        page: 頁碼（預設 1）
        per_page: 每頁筆數（預設 20，最大 100）
    """
    client = get_client()
    result = client.list_projects(search=search, page=page, per_page=per_page)
    return json.dumps(result, ensure_ascii=False, indent=2)
```

### Phase 1 完整工具清單（30 tools）

#### Projects（3）
1. `list_projects(search, page, per_page)` — 列出可存取的專案
2. `get_project(project_id)` — 取得專案詳情
3. `list_project_members(project_id, page, per_page)` — 列出專案成員

#### Merge Requests（10）
4. `list_merge_requests(project_id, state, page, per_page)` — 列出 MR
5. `get_merge_request(project_id, mr_iid)` — 取得 MR 詳情
6. `create_merge_request(project_id, source_branch, target_branch, title, description, assignee_id, reviewer_ids)` — 建立 MR
7. `update_merge_request(project_id, mr_iid, title, description, state_event, assignee_id, reviewer_ids)` — 更新 MR
8. `merge_merge_request(project_id, mr_iid, merge_commit_message, should_remove_source_branch)` — 合併 MR
9. `approve_merge_request(project_id, mr_iid)` — 核准 MR
10. `get_merge_request_changes(project_id, mr_iid)` — 取得 MR 檔案變更
11. `get_merge_request_commits(project_id, mr_iid)` — 取得 MR 的 commits
12. `list_merge_request_notes(project_id, mr_iid, page, per_page)` — 列出 MR 留言
13. `create_merge_request_note(project_id, mr_iid, body)` — 新增 MR 留言

#### CI/CD Pipelines & Jobs（9）
14. `list_pipelines(project_id, status, ref, page, per_page)` — 列出 Pipelines
15. `get_pipeline(project_id, pipeline_id)` — 取得 Pipeline 詳情
16. `create_pipeline(project_id, ref, variables)` — 觸發新 Pipeline
17. `retry_pipeline(project_id, pipeline_id)` — 重試 Pipeline
18. `cancel_pipeline(project_id, pipeline_id)` — 取消 Pipeline
19. `list_pipeline_jobs(project_id, pipeline_id, page, per_page)` — 列出 Pipeline Jobs
20. `get_job(project_id, job_id)` — 取得 Job 詳情
21. `get_job_log(project_id, job_id)` — 取得 Job 執行日誌
22. `retry_job(project_id, job_id)` — 重試單一 Job

#### Repository（6）
23. `list_branches(project_id, search, page, per_page)` — 列出分支
24. `get_branch(project_id, branch_name)` — 取得分支詳情
25. `list_commits(project_id, ref_name, path, page, per_page)` — 列出 Commits
26. `get_commit(project_id, sha)` — 取得 Commit 詳情
27. `compare_branches(project_id, from_ref, to_ref)` — 比較兩個分支差異
28. `list_repository_tree(project_id, path, ref, recursive)` — 瀏覽檔案結構

#### 管理工具（2）
29. `server_info()` — 顯示 GitLab 連線資訊與版本
30. `health_check()` — 檢查 GitLab API 連線狀態

## 6. 驗證設計 (`validators.py`)

```python
@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str]
    warnings: list[str]

class GitLabValidator:
    MAX_TITLE_LENGTH = 255
    MAX_DESCRIPTION_LENGTH = 1_048_576  # 1MB
    VALID_MR_STATES = {"opened", "closed", "merged", "all"}
    VALID_PIPELINE_STATUSES = {"running", "pending", "success", "failed", "canceled", "skipped"}
    VALID_MR_STATE_EVENTS = {"close", "reopen"}

    @classmethod
    def validate_project_id(cls, project_id: int | str) -> ValidationResult:
        """驗證 project_id（支援數字 ID 或 URL-encoded path）"""

    @classmethod
    def validate_merge_request_data(cls, data: dict, is_update: bool = False) -> ValidationResult:
        """驗證 MR 建立/更新資料"""

    @classmethod
    def validate_pipeline_data(cls, data: dict) -> ValidationResult:
        """驗證 Pipeline 觸發資料"""

    @classmethod
    def get_friendly_error_message(cls, error: Exception, context: str) -> str:
        """技術錯誤轉人類友好訊息"""
```

## 7. 錯誤處理策略

### 分層錯誤處理

```
Layer 1 (底層): requests 異常 → ConnectionError, Timeout, HTTPError
    ↓
Layer 2 (客戶端): GitLabAPIError — 附帶 status_code 和 response_data
    ↓
Layer 3 (工具層): 捕獲 GitLabAPIError → 回傳友善文字訊息給 AI
```

### HTTP 狀態碼對照

| 狀態碼 | 訊息 |
|--------|------|
| 401 | 認證失敗：請檢查 Personal Access Token |
| 403 | 權限不足：Token 缺少所需權限範圍 |
| 404 | 找不到資源：請確認 ID 是否正確 |
| 405 | 此操作不被允許（如：合併已關閉的 MR） |
| 409 | 衝突：資源狀態不允許此操作 |
| 422 | 驗證失敗：請檢查輸入參數 |
| 429 | 請求頻率過高，請稍後再試 |
| 500+ | GitLab 伺服器錯誤 |

## 8. 分頁處理

GitLab API 使用 Header-based 分頁：

```python
def _get_paginated(self, endpoint: str, params: dict = None, max_pages: int = None) -> list:
    """
    處理 GitLab 分頁回應。

    GitLab 回應 Header：
    - X-Page: 目前頁碼
    - X-Per-Page: 每頁筆數
    - X-Total: 總筆數
    - X-Total-Pages: 總頁數
    - X-Next-Page: 下一頁頁碼
    """
    results = []
    while endpoint:
        response = self._make_request("GET", endpoint, params=params)
        results.extend(response)
        # 檢查是否有下一頁
        next_page = response.headers.get("X-Next-Page")
        if not next_page or (max_pages and current_page >= max_pages):
            break
        params["page"] = int(next_page)
    return results
```

## 9. Docker 部署

### Dockerfile

```dockerfile
# Stage 1: Builder
FROM python:3.12-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src/ src/

# Stage 2: Runtime
FROM python:3.12-slim AS runtime
RUN useradd --create-home --shell /bin/bash mcp
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV GITLAB_MCP_TRANSPORT=sse
ENV GITLAB_MCP_HOST=0.0.0.0
ENV GITLAB_MCP_PORT=8000
USER mcp
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -sf http://localhost:8000/sse || exit 1
CMD ["python", "-m", "gitlab_mcp.server", "--transport", "sse"]
```

### docker-compose.yml

```yaml
services:
  gitlab-mcp:
    build: .
    container_name: gitlab-mcp
    ports:
      - "${GITLAB_MCP_PORT:-8000}:8000"
    environment:
      - GITLAB_URL=${GITLAB_URL}
      - GITLAB_TOKEN=${GITLAB_TOKEN}
      - GITLAB_MCP_TRANSPORT=sse
      - GITLAB_MCP_LOG_LEVEL=${GITLAB_MCP_LOG_LEVEL:-INFO}
      - GITLAB_TIMEOUT=${GITLAB_TIMEOUT:-30}
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8000/sse"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 5s
```

### MCP 客戶端設定

```json
{
  "mcpServers": {
    "gitlab": {
      "type": "sse",
      "url": "http://localhost:8000/sse"
    }
  }
}
```

## 10. 實作計畫

### Phase 1（本次實作）— 30 tools

1. 專案骨架：pyproject.toml, Dockerfile, docker-compose.yml, .env.example
2. `config.py` — 配置管理
3. `validators.py` — 輸入驗證
4. `gitlab_client.py` — API 客戶端（Projects, MR, Pipeline, Repository）
5. `server.py` — MCP server + 30 tools 註冊
6. Docker 建置與測試

### Phase 2（未來）— Issues, Search, Users

- Issues CRUD + notes
- 全域搜尋
- 使用者查詢與管理

### Phase 3（未來）— 完整覆蓋

- Labels, Milestones
- Groups
- Wikis, Snippets

## 11. GitLab 14.10.5 相容性注意事項

- **MR Reviewers**：reviewer 功能在 13.7 引入，14.10.5 可用
- **MR Approve**：需要 GitLab Premium/Ultimate 或已安裝 CE approvals
- **Pipeline variables**：`POST /pipeline` 的 `variables` 參數在 14.x 可用
- **分頁 Header**：`X-Total`, `X-Total-Pages` 在部分 API 可能不回傳，需處理
- **Project path 作為 ID**：需 URL encode（`group%2Fproject`）
