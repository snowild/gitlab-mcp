# GitLab MCP Server

GitLab MCP Server — 透過 Model Context Protocol 讓 AI 助手（Claude Code、Cursor 等）直接操作自架 GitLab。

支援 GitLab 14.x+ REST API v4，使用 Personal Access Token 認證。

## 安裝與部署

### 前置需求

- Docker
- GitLab Personal Access Token（權限範圍：`api`, `read_user`）
  - 取得方式：GitLab > User Settings > Access Tokens

### Docker 部署（多 target，建議）

一個 container 同時服務多台 GitLab，各 tool 以 `target_id` 選台；token 從個人憑證檔讀，不放進 container 的環境變數（`docker inspect` 看不到）。

1. 個人憑證檔 `~/.larvata/credentials.json`（權限 `600`，key 隨意，以 `url` 的 origin 對應 target）：

   ```json
   {
     "gitlab-larvata": { "url": "https://gitlab.example.com", "token": "glpat-..." },
     "gitlab-larvata-new": { "url": "https://gitlab-new.example.com", "token": "glpat-..." }
   }
   ```

2. 非機密設定 `~/.larvata/gitlab-mcp.env`：

   ```bash
   GITLAB_MCP_TRANSPORT=sse
   GITLAB_MCP_HOST=0.0.0.0
   GITLAB_MCP_PORT=8000
   GITLAB_CREDENTIALS_FILE=/creds.json
   GITLAB_TARGETS_JSON=[{"id":"larvata","url":"https://gitlab.example.com","default":true},{"id":"larvata-new","url":"https://gitlab-new.example.com"}]
   ```

3. 建置與啟動：

   ```bash
   docker build -t gitlab-mcp .
   docker run -d --name gitlab-mcp \
     --user $(id -u):$(id -g) \
     --env-file ~/.larvata/gitlab-mcp.env \
     -v ~/.larvata/credentials.json:/creds.json:ro \
     -p 127.0.0.1:8001:8000 \
     --restart unless-stopped \
     gitlab-mcp
   ```

`--user` 讓 container 能讀權限 `600` 的憑證檔。憑證檔每次呼叫都重讀，補好 token 不必重啟。用 `list_targets` 看各台的憑證狀態（`present`／`missing`／`ambiguous`／`file_error`）。

### Docker 部署（單台相容模式）

沒設 `GITLAB_TARGETS_JSON` 時，照舊讀 `GITLAB_URL`／`GITLAB_TOKEN`，target id 為 `default`：

```bash
# 1. 建置 image
docker compose build

# 2. 建立 .env 檔案
cp .env.example .env
# 編輯 .env，填入 GITLAB_URL 和 GITLAB_TOKEN

# 3. 啟動服務
docker compose up -d
```

### MCP 客戶端設定

在 Claude Code 或其他 MCP 客戶端中加入：

```json
{
  "mcpServers": {
    "gitlab": {
      "type": "sse",
      "url": "http://localhost:8001/sse"
    }
  }
}
```

## 環境變數

| 變數 | 必填 | 預設值 | 說明 |
|------|------|--------|------|
| `GITLAB_TARGETS_JSON` | 多 target | — | target 清單：`[{"id","url","default"}]`，url 須 https、恰好一台 `default: true`（只有一台可省略） |
| `GITLAB_CREDENTIALS_FILE` | 多 target | — | 憑證檔在 container 內的路徑（如 `/creds.json`） |
| `GITLAB_URL` | 相容模式 | — | GitLab 位址（設了 `GITLAB_TARGETS_JSON` 就不用） |
| `GITLAB_TOKEN` | 相容模式 | — | Personal Access Token（多 target 模式下被忽略） |
| `GITLAB_MCP_TRANSPORT` | No | `stdio` | 傳輸模式（`stdio` / `sse`） |
| `GITLAB_MCP_HOST` | No | `0.0.0.0` | SSE 監聽位址 |
| `GITLAB_MCP_PORT` | No | `8000` | SSE 監聽端口 |
| `GITLAB_MCP_LOG_LEVEL` | No | `INFO` | 日誌等級 |
| `GITLAB_TIMEOUT` | No | `30` | API 請求逾時（秒） |

## 功能列表（31 tools）

除 `list_targets` 外，每個 tool 都有選填參數 `target_id`，省略時用預設台。

### 管理工具

| Tool | 說明 |
|------|------|
| `list_targets` | 列出各 GitLab 主機與憑證狀態（不含 token） |
| `server_info` | 取得伺服器資訊與 GitLab 版本 |
| `health_check` | 檢查連線狀態；不帶 `target_id` 時逐台檢查 |

### Projects

| Tool | 說明 |
|------|------|
| `list_projects` | 列出可存取的專案（支援搜尋） |
| `get_project` | 取得專案詳情 |
| `list_project_members` | 列出專案成員 |

### Merge Requests

| Tool | 說明 |
|------|------|
| `list_merge_requests` | 列出 MR（可依狀態篩選） |
| `get_merge_request` | 取得 MR 詳情 |
| `create_merge_request` | 建立 MR |
| `update_merge_request` | 更新 MR（標題、描述、指派、狀態） |
| `merge_merge_request` | 執行合併 |
| `approve_merge_request` | 核准 MR |
| `get_merge_request_changes` | 取得 MR 檔案變更（diff） |
| `get_merge_request_commits` | 取得 MR 包含的 commits |
| `list_merge_request_notes` | 列出 MR 留言 |
| `create_merge_request_note` | 新增 MR 留言 |

### CI/CD Pipelines & Jobs

| Tool | 說明 |
|------|------|
| `list_pipelines` | 列出 Pipelines（可依狀態、分支篩選） |
| `get_pipeline` | 取得 Pipeline 詳情 |
| `create_pipeline` | 觸發新 Pipeline |
| `retry_pipeline` | 重試 Pipeline |
| `cancel_pipeline` | 取消 Pipeline |
| `list_pipeline_jobs` | 列出 Pipeline 的 Jobs |
| `get_job` | 取得 Job 詳情 |
| `get_job_log` | 取得 Job 執行日誌 |
| `retry_job` | 重試單一 Job |

### Repository

| Tool | 說明 |
|------|------|
| `list_branches` | 列出分支 |
| `get_branch` | 取得分支詳情 |
| `list_commits` | 列出 Commits |
| `get_commit` | 取得 Commit 詳情 |
| `compare_branches` | 比較兩個分支差異 |
| `list_repository_tree` | 瀏覽檔案結構 |

## 開發

```bash
# 安裝依賴（需要 uv）
uv sync

# 本地啟動（stdio 模式）
uv run gitlab-mcp

# 本地啟動（SSE 模式）
uv run gitlab-mcp --transport sse --port 8001
```

## License

MIT
