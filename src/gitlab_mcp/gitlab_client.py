"""
GitLab REST API v4 客戶端
處理與 GitLab 伺服器的所有 HTTP 通訊
"""

import json
import logging
from typing import Optional
from urllib.parse import quote

import requests

from .config import get_config, reload_config
from .credentials import Credential, lookup_credentials
from .targets import Target

logger = logging.getLogger(__name__)


class GitLabAPIError(Exception):
    """GitLab API 錯誤"""

    def __init__(self, message: str, status_code: int = None, response_data: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class GitLabClient:
    """GitLab REST API v4 客戶端"""

    def __init__(self, target_id: str, base_url: str, token: str, timeout: int):
        self.target_id = target_id
        self.base_url = base_url
        self.api_base_url = f"{base_url}/api/v4"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
        })

    # ------------------------------------------------------------------
    # 內部輔助方法
    # ------------------------------------------------------------------

    def _resolve_project_id(self, project_id: int | str) -> str:
        """解析 project_id，支援數字 ID 或 URL-encoded path"""
        if isinstance(project_id, int):
            return str(project_id)
        # 若包含 /，視為路徑並做 URL encode
        if "/" in str(project_id):
            return quote(str(project_id), safe="")
        return str(project_id)

    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """
        統一 HTTP 請求處理

        Returns:
            requests.Response object（由呼叫端決定如何解析）
        """
        url = f"{self.api_base_url}{endpoint}"

        try:
            response = self.session.request(
                method, url, timeout=self.timeout, **kwargs
            )
            response.raise_for_status()
            return response

        except requests.exceptions.Timeout:
            raise GitLabAPIError(
                f"[{self.target_id}] 請求逾時（{self.timeout}秒）：{method} {endpoint}",
                status_code=408,
            )
        except requests.exceptions.ConnectionError:
            raise GitLabAPIError(
                f"[{self.target_id}] 無法連接到 GitLab 伺服器：{self.base_url}",
                status_code=0,
            )
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code
            try:
                response_data = e.response.json()
            except (json.JSONDecodeError, ValueError):
                response_data = {"error": e.response.text}

            error_messages = {
                401: "認證失敗：請檢查 Personal Access Token",
                403: "權限不足，或未連 VPN",
                404: "找不到資源：請確認 ID 或路徑是否正確",
                405: "此操作不被允許",
                409: "衝突：資源狀態不允許此操作",
                422: "驗證失敗：請檢查輸入參數",
                429: "請求頻率過高，請稍後再試",
            }

            message = error_messages.get(
                status_code, f"GitLab API 錯誤（HTTP {status_code}）"
            )

            # 附加 response 中的錯誤詳情
            if isinstance(response_data, dict):
                detail = response_data.get("message") or response_data.get("error")
                if detail:
                    message = f"{message}：{detail}"

            raise GitLabAPIError(
                f"[{self.target_id}] {message}", status_code=status_code, response_data=response_data
            )
        except requests.exceptions.RequestException as e:
            # 其他例外的訊息可能含 header 值（token），只回類別名稱
            raise GitLabAPIError(
                f"[{self.target_id}] 請求失敗（{type(e).__name__}）：{method} {endpoint}",
                status_code=0,
            )

    def _get_json(self, endpoint: str, params: dict = None) -> dict | list:
        """GET 請求，回傳 JSON"""
        response = self._make_request("GET", endpoint, params=params)
        return response.json()

    def _post_json(self, endpoint: str, data: dict = None) -> dict:
        """POST 請求，回傳 JSON"""
        response = self._make_request("POST", endpoint, json=data)
        return response.json()

    def _put_json(self, endpoint: str, data: dict = None) -> dict:
        """PUT 請求，回傳 JSON"""
        response = self._make_request("PUT", endpoint, json=data)
        return response.json()

    def _get_text(self, endpoint: str, params: dict = None) -> str:
        """GET 請求，回傳純文字（用於 job logs）"""
        response = self._make_request(
            "GET", endpoint, params=params, headers={"Accept": "text/plain"}
        )
        return response.text

    # ------------------------------------------------------------------
    # 伺服器資訊
    # ------------------------------------------------------------------

    def get_server_version(self) -> dict:
        """GET /version — 取得 GitLab 版本資訊"""
        return self._get_json("/version")

    def test_connection(self) -> bool:
        """測試與 GitLab 的連線"""
        try:
            self.get_server_version()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Projects API
    # ------------------------------------------------------------------

    def list_projects(
        self,
        search: str = None,
        membership: bool = True,
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict]:
        """GET /projects"""
        params = {"page": page, "per_page": per_page, "membership": membership}
        if search:
            params["search"] = search
        return self._get_json("/projects", params=params)

    def get_project(self, project_id: int | str) -> dict:
        """GET /projects/:id"""
        pid = self._resolve_project_id(project_id)
        return self._get_json(f"/projects/{pid}")

    def list_project_members(
        self, project_id: int | str, page: int = 1, per_page: int = 20
    ) -> list[dict]:
        """GET /projects/:id/members"""
        pid = self._resolve_project_id(project_id)
        params = {"page": page, "per_page": per_page}
        return self._get_json(f"/projects/{pid}/members", params=params)

    # ------------------------------------------------------------------
    # Merge Requests API
    # ------------------------------------------------------------------

    def list_merge_requests(
        self,
        project_id: int | str,
        state: str = None,
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict]:
        """GET /projects/:id/merge_requests"""
        pid = self._resolve_project_id(project_id)
        params = {"page": page, "per_page": per_page}
        if state:
            params["state"] = state
        return self._get_json(f"/projects/{pid}/merge_requests", params=params)

    def get_merge_request(self, project_id: int | str, mr_iid: int) -> dict:
        """GET /projects/:id/merge_requests/:iid"""
        pid = self._resolve_project_id(project_id)
        return self._get_json(f"/projects/{pid}/merge_requests/{mr_iid}")

    def create_merge_request(
        self,
        project_id: int | str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str = None,
        assignee_id: int = None,
        reviewer_ids: list[int] = None,
    ) -> dict:
        """POST /projects/:id/merge_requests"""
        pid = self._resolve_project_id(project_id)
        data = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
        }
        if description is not None:
            data["description"] = description
        if assignee_id is not None:
            data["assignee_id"] = assignee_id
        if reviewer_ids is not None:
            data["reviewer_ids"] = reviewer_ids
        return self._post_json(f"/projects/{pid}/merge_requests", data=data)

    def update_merge_request(
        self, project_id: int | str, mr_iid: int, **kwargs
    ) -> dict:
        """PUT /projects/:id/merge_requests/:iid

        支援的 kwargs: title, description, state_event (close/reopen),
        assignee_id, reviewer_ids, target_branch
        """
        pid = self._resolve_project_id(project_id)
        # 僅包含非 None 值
        data = {k: v for k, v in kwargs.items() if v is not None}
        return self._put_json(f"/projects/{pid}/merge_requests/{mr_iid}", data=data)

    def merge_merge_request(
        self,
        project_id: int | str,
        mr_iid: int,
        merge_commit_message: str = None,
        should_remove_source_branch: bool = False,
    ) -> dict:
        """PUT /projects/:id/merge_requests/:iid/merge"""
        pid = self._resolve_project_id(project_id)
        data = {}
        if merge_commit_message:
            data["merge_commit_message"] = merge_commit_message
        if should_remove_source_branch:
            data["should_remove_source_branch"] = True
        return self._put_json(
            f"/projects/{pid}/merge_requests/{mr_iid}/merge", data=data
        )

    def approve_merge_request(self, project_id: int | str, mr_iid: int) -> dict:
        """POST /projects/:id/merge_requests/:iid/approve"""
        pid = self._resolve_project_id(project_id)
        return self._post_json(f"/projects/{pid}/merge_requests/{mr_iid}/approve")

    def get_merge_request_changes(self, project_id: int | str, mr_iid: int) -> dict:
        """GET /projects/:id/merge_requests/:iid/changes"""
        pid = self._resolve_project_id(project_id)
        return self._get_json(f"/projects/{pid}/merge_requests/{mr_iid}/changes")

    def get_merge_request_commits(
        self, project_id: int | str, mr_iid: int
    ) -> list[dict]:
        """GET /projects/:id/merge_requests/:iid/commits"""
        pid = self._resolve_project_id(project_id)
        return self._get_json(f"/projects/{pid}/merge_requests/{mr_iid}/commits")

    def list_merge_request_notes(
        self,
        project_id: int | str,
        mr_iid: int,
        sort: str = "asc",
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict]:
        """GET /projects/:id/merge_requests/:iid/notes"""
        pid = self._resolve_project_id(project_id)
        params = {"sort": sort, "page": page, "per_page": per_page}
        return self._get_json(
            f"/projects/{pid}/merge_requests/{mr_iid}/notes", params=params
        )

    def create_merge_request_note(
        self, project_id: int | str, mr_iid: int, body: str
    ) -> dict:
        """POST /projects/:id/merge_requests/:iid/notes"""
        pid = self._resolve_project_id(project_id)
        return self._post_json(
            f"/projects/{pid}/merge_requests/{mr_iid}/notes", data={"body": body}
        )

    # ------------------------------------------------------------------
    # CI/CD Pipelines & Jobs API
    # ------------------------------------------------------------------

    def list_pipelines(
        self,
        project_id: int | str,
        status: str = None,
        ref: str = None,
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict]:
        """GET /projects/:id/pipelines"""
        pid = self._resolve_project_id(project_id)
        params = {"page": page, "per_page": per_page}
        if status:
            params["status"] = status
        if ref:
            params["ref"] = ref
        return self._get_json(f"/projects/{pid}/pipelines", params=params)

    def get_pipeline(self, project_id: int | str, pipeline_id: int) -> dict:
        """GET /projects/:id/pipelines/:pipeline_id"""
        pid = self._resolve_project_id(project_id)
        return self._get_json(f"/projects/{pid}/pipelines/{pipeline_id}")

    def create_pipeline(
        self, project_id: int | str, ref: str, variables: list[dict] = None
    ) -> dict:
        """POST /projects/:id/pipeline"""
        pid = self._resolve_project_id(project_id)
        data = {"ref": ref}
        if variables:
            data["variables"] = variables
        return self._post_json(f"/projects/{pid}/pipeline", data=data)

    def retry_pipeline(self, project_id: int | str, pipeline_id: int) -> dict:
        """POST /projects/:id/pipelines/:pipeline_id/retry"""
        pid = self._resolve_project_id(project_id)
        return self._post_json(f"/projects/{pid}/pipelines/{pipeline_id}/retry")

    def cancel_pipeline(self, project_id: int | str, pipeline_id: int) -> dict:
        """POST /projects/:id/pipelines/:pipeline_id/cancel"""
        pid = self._resolve_project_id(project_id)
        return self._post_json(f"/projects/{pid}/pipelines/{pipeline_id}/cancel")

    def list_pipeline_jobs(
        self,
        project_id: int | str,
        pipeline_id: int,
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict]:
        """GET /projects/:id/pipelines/:pipeline_id/jobs"""
        pid = self._resolve_project_id(project_id)
        params = {"page": page, "per_page": per_page}
        return self._get_json(
            f"/projects/{pid}/pipelines/{pipeline_id}/jobs", params=params
        )

    def get_job(self, project_id: int | str, job_id: int) -> dict:
        """GET /projects/:id/jobs/:job_id"""
        pid = self._resolve_project_id(project_id)
        return self._get_json(f"/projects/{pid}/jobs/{job_id}")

    def get_job_log(self, project_id: int | str, job_id: int) -> str:
        """GET /projects/:id/jobs/:job_id/trace — 回傳純文字日誌"""
        pid = self._resolve_project_id(project_id)
        return self._get_text(f"/projects/{pid}/jobs/{job_id}/trace")

    def retry_job(self, project_id: int | str, job_id: int) -> dict:
        """POST /projects/:id/jobs/:job_id/retry"""
        pid = self._resolve_project_id(project_id)
        return self._post_json(f"/projects/{pid}/jobs/{job_id}/retry")

    # ------------------------------------------------------------------
    # Repository API
    # ------------------------------------------------------------------

    def list_branches(
        self,
        project_id: int | str,
        search: str = None,
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict]:
        """GET /projects/:id/repository/branches"""
        pid = self._resolve_project_id(project_id)
        params = {"page": page, "per_page": per_page}
        if search:
            params["search"] = search
        return self._get_json(f"/projects/{pid}/repository/branches", params=params)

    def get_branch(self, project_id: int | str, branch_name: str) -> dict:
        """GET /projects/:id/repository/branches/:branch"""
        pid = self._resolve_project_id(project_id)
        encoded_branch = quote(branch_name, safe="")
        return self._get_json(
            f"/projects/{pid}/repository/branches/{encoded_branch}"
        )

    def list_commits(
        self,
        project_id: int | str,
        ref_name: str = None,
        path: str = None,
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict]:
        """GET /projects/:id/repository/commits"""
        pid = self._resolve_project_id(project_id)
        params = {"page": page, "per_page": per_page}
        if ref_name:
            params["ref_name"] = ref_name
        if path:
            params["path"] = path
        return self._get_json(f"/projects/{pid}/repository/commits", params=params)

    def get_commit(self, project_id: int | str, sha: str) -> dict:
        """GET /projects/:id/repository/commits/:sha"""
        pid = self._resolve_project_id(project_id)
        return self._get_json(f"/projects/{pid}/repository/commits/{sha}")

    def compare_branches(
        self, project_id: int | str, from_ref: str, to_ref: str
    ) -> dict:
        """GET /projects/:id/repository/compare"""
        pid = self._resolve_project_id(project_id)
        params = {"from": from_ref, "to": to_ref}
        return self._get_json(f"/projects/{pid}/repository/compare", params=params)

    def list_repository_tree(
        self,
        project_id: int | str,
        path: str = "",
        ref: str = None,
        recursive: bool = False,
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict]:
        """GET /projects/:id/repository/tree"""
        pid = self._resolve_project_id(project_id)
        params = {"page": page, "per_page": per_page}
        if path:
            params["path"] = path
        if ref:
            params["ref"] = ref
        if recursive:
            params["recursive"] = True
        return self._get_json(f"/projects/{pid}/repository/tree", params=params)


# ------------------------------------------------------------------
# 全域客戶端實例
# ------------------------------------------------------------------

_clients: dict[str, GitLabClient] = {}


class TargetError(GitLabAPIError):
    """target_id 未知，或該 target 沒有可用 token（不發 request）"""


def target_states() -> list[tuple[Target, Credential]]:
    """各 target 與其憑證狀態；相容模式不讀憑證檔"""
    config = get_config()
    if not config.multi_target:
        return [(t, Credential("present")) for t in config.targets]
    creds = lookup_credentials(config.credentials_file, config.targets)
    return [(t, creds[t.id]) for t in config.targets]


def state_message(target: Target, cred: Credential, path: Optional[str]) -> str:
    if cred.state == "missing":
        return f"[{target.id}] 憑證檔 {path} 沒有 url 為 {target.url} 的 token，請加一筆"
    if cred.state == "ambiguous":
        return f"[{target.id}] 憑證檔 {path} 有多筆 url 為 {target.url} 的 token，請刪到剩一筆"
    return f"[{target.id}] {cred.error}"


def get_client(target_id: Optional[str] = None) -> GitLabClient:
    """依 target_id 取得客戶端；None 為預設 target。每次呼叫重讀憑證檔"""
    config = get_config()
    if target_id is None:
        target = config.default_target
    else:
        target = next((t for t in config.targets if t.id == target_id), None)
        if target is None:
            ids = ", ".join(t.id for t in config.targets)
            raise TargetError(f"未知的 target_id '{target_id}'，可用：{ids}")

    if config.multi_target:
        cred = lookup_credentials(config.credentials_file, [target])[target.id]
        if cred.state != "present":
            raise TargetError(state_message(target, cred, config.credentials_file))
        token = cred.token
    else:
        token = target.legacy_token

    client = _clients.get(target.id)
    if client is None or client.session.headers.get("PRIVATE-TOKEN") != token:
        client = GitLabClient(target.id, target.url, token, config.timeout)
        _clients[target.id] = client
    return client


def reload_client() -> None:
    """清空客戶端快取並重讀配置（主要用於測試）"""
    _clients.clear()
    reload_config()
