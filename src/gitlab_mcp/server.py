"""
GitLab MCP 服務器主程式
提供與 GitLab 系統整合的 MCP 工具
"""

import json
import argparse
import logging

# 確保配置在 FastMCP 初始化之前載入
from .config import get_config
config = get_config()

from mcp.server.fastmcp import FastMCP
from .gitlab_client import get_client, GitLabAPIError
from .validators import GitLabValidator

logger = logging.getLogger(__name__)

# 建立 FastMCP 服務器實例
mcp = FastMCP("GitLab MCP")


# ======================================================================
# 管理工具 (Admin Tools)
# ======================================================================


@mcp.tool()
def server_info() -> str:
    """取得 GitLab MCP 服務器資訊和連線狀態"""
    config = get_config()
    try:
        client = get_client()
        version_info = client.get_server_version()
        gitlab_version = version_info.get("version", "未知")
        return f"""GitLab MCP 服務器已啟動
- GitLab 位址: {config.gitlab_url}
- GitLab 版本: {gitlab_version}
- API 逾時: {config.timeout}秒
- 日誌級別: {config.log_level}"""
    except GitLabAPIError as e:
        return f"""GitLab MCP 服務器已啟動（無法取得版本資訊）
- GitLab 位址: {config.gitlab_url}
- 連線錯誤: {str(e)}"""


@mcp.tool()
def health_check() -> str:
    """健康檢查，確認與 GitLab 伺服器的連線狀態"""
    try:
        client = get_client()
        config = get_config()
        if client.test_connection():
            version_info = client.get_server_version()
            return f"✓ 連線正常 — {config.gitlab_url}（GitLab {version_info.get('version', '?')}）"
        else:
            return f"✗ 無法連接到 {config.gitlab_url}"
    except Exception as e:
        return f"✗ 連線異常: {str(e)}"


# ======================================================================
# 專案工具 (Projects Tools)
# ======================================================================


@mcp.tool()
def list_projects(search: str = None, membership: bool = True,
                  page: int = 1, per_page: int = 20) -> str:
    """列出可存取的 GitLab 專案

    Args:
        search: 搜尋關鍵字（專案名稱）
        membership: 僅列出已加入的專案（預設 True）
        page: 頁碼（預設 1）
        per_page: 每頁筆數（預設 20，最大 100）
    """
    try:
        client = get_client()
        projects = client.list_projects(search=search, membership=membership,
                                        page=page, per_page=per_page)
        if not projects:
            return "找不到符合條件的專案"

        lines = [f"找到 {len(projects)} 個專案：\n"]
        for p in projects:
            desc = p.get("description") or ""
            if len(desc) > 60:
                desc = desc[:60] + "..."
            lines.append(
                f"- [{p['id']}] {p['path_with_namespace']}"
                f"\n  {desc}"
                f"\n  預設分支: {p.get('default_branch', 'N/A')} | {p.get('web_url', '')}\n"
            )
        return "\n".join(lines)
    except GitLabAPIError as e:
        return f"列出專案失敗: {str(e)}"


@mcp.tool()
def get_project(project_id: int | str) -> str:
    """取得 GitLab 專案詳細資訊

    Args:
        project_id: 專案 ID（數字）或路徑（如 group/project）
    """
    try:
        client = get_client()
        p = client.get_project(project_id)
        return f"""專案: {p['name']} [{p['id']}]
路徑: {p['path_with_namespace']}
描述: {p.get('description') or '無'}
預設分支: {p.get('default_branch', 'N/A')}
可見性: {p.get('visibility', 'N/A')}
建立時間: {p.get('created_at', 'N/A')}
最後活動: {p.get('last_activity_at', 'N/A')}
星標數: {p.get('star_count', 0)} | Fork 數: {p.get('forks_count', 0)}
網址: {p.get('web_url', '')}"""
    except GitLabAPIError as e:
        return f"取得專案失敗: {str(e)}"


@mcp.tool()
def list_project_members(project_id: int | str, page: int = 1,
                         per_page: int = 20) -> str:
    """列出專案成員

    Args:
        project_id: 專案 ID 或路徑
        page: 頁碼
        per_page: 每頁筆數
    """
    try:
        client = get_client()
        members = client.list_project_members(project_id, page=page, per_page=per_page)
        if not members:
            return "此專案沒有成員"

        access_levels = {10: "Guest", 20: "Reporter", 30: "Developer", 40: "Maintainer", 50: "Owner"}
        lines = [f"專案成員（共 {len(members)} 位）：\n"]
        for m in members:
            level = access_levels.get(m.get("access_level", 0), "Unknown")
            lines.append(f"- {m.get('name', 'N/A')} (@{m.get('username', 'N/A')}) — {level}")
        return "\n".join(lines)
    except GitLabAPIError as e:
        return f"列出成員失敗: {str(e)}"


# ======================================================================
# Merge Request 工具
# ======================================================================


@mcp.tool()
def list_merge_requests(project_id: int | str, state: str = None,
                        page: int = 1, per_page: int = 20) -> str:
    """列出專案的 Merge Requests

    Args:
        project_id: 專案 ID 或路徑
        state: 狀態篩選（opened, closed, merged, all）
        page: 頁碼
        per_page: 每頁筆數
    """
    try:
        if state:
            v = GitLabValidator.validate_mr_state(state)
            if not v.is_valid:
                return "\n".join(v.errors)

        client = get_client()
        mrs = client.list_merge_requests(project_id, state=state, page=page, per_page=per_page)
        if not mrs:
            return "找不到符合條件的 Merge Request"

        status_emoji = {"opened": "🟢", "closed": "🔴", "merged": "🟣"}
        lines = [f"找到 {len(mrs)} 個 Merge Request：\n"]
        for mr in mrs:
            emoji = status_emoji.get(mr.get("state", ""), "⚪")
            lines.append(
                f"{emoji} !{mr['iid']} [{mr.get('state', '')}] {mr['title']}"
                f"\n  {mr.get('source_branch', '')} → {mr.get('target_branch', '')}"
                f"\n  作者: {mr.get('author', {}).get('name', 'N/A')} | {mr.get('web_url', '')}\n"
            )
        return "\n".join(lines)
    except GitLabAPIError as e:
        return f"列出 MR 失敗: {str(e)}"


@mcp.tool()
def get_merge_request(project_id: int | str, mr_iid: int) -> str:
    """取得 Merge Request 詳細資訊

    Args:
        project_id: 專案 ID 或路徑
        mr_iid: MR 的 IID（專案內編號）
    """
    try:
        client = get_client()
        mr = client.get_merge_request(project_id, mr_iid)

        status_emoji = {"opened": "🟢", "closed": "🔴", "merged": "🟣"}
        emoji = status_emoji.get(mr.get("state", ""), "⚪")

        assignee = mr.get("assignee")
        assignee_str = f"{assignee['name']} (@{assignee['username']})" if assignee else "未指派"

        reviewers = mr.get("reviewers", [])
        reviewer_str = ", ".join(f"{r['name']}" for r in reviewers) if reviewers else "無"

        pipeline = mr.get("pipeline")
        pipeline_str = f"#{pipeline['id']} ({pipeline['status']})" if pipeline else "無"

        result = f"""{emoji} Merge Request !{mr['iid']}
標題: {mr['title']}
狀態: {mr.get('state', 'N/A')}
來源分支: {mr.get('source_branch', 'N/A')} → 目標分支: {mr.get('target_branch', 'N/A')}
作者: {mr.get('author', {}).get('name', 'N/A')}
指派: {assignee_str}
審核者: {reviewer_str}
Pipeline: {pipeline_str}
建立時間: {mr.get('created_at', 'N/A')}
更新時間: {mr.get('updated_at', 'N/A')}
網址: {mr.get('web_url', '')}"""

        if mr.get('merged_at'):
            result += f"\n合併時間: {mr['merged_at']}"
            merged_by = mr.get('merged_by')
            if merged_by:
                result += f"\n合併者: {merged_by.get('name', 'N/A')}"

        if mr.get('description'):
            result += f"\n\n--- 描述 ---\n{mr['description']}"

        return result
    except GitLabAPIError as e:
        return f"取得 MR 失敗: {str(e)}"


@mcp.tool()
def create_merge_request(project_id: int | str, source_branch: str,
                         target_branch: str, title: str,
                         description: str = None, assignee_id: int = None,
                         reviewer_ids: str = None) -> str:
    """建立新的 Merge Request

    Args:
        project_id: 專案 ID 或路徑
        source_branch: 來源分支
        target_branch: 目標分支
        title: MR 標題
        description: MR 描述
        assignee_id: 指派人 ID
        reviewer_ids: 審核者 ID 列表（逗號分隔，如 "1,2,3"）
    """
    try:
        v = GitLabValidator.validate_merge_request_data({
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
        })
        if not v.is_valid:
            return "驗證失敗：\n" + "\n".join(v.errors)

        # 解析逗號分隔的 reviewer_ids
        parsed_reviewer_ids = None
        if reviewer_ids:
            try:
                parsed_reviewer_ids = [int(x.strip()) for x in reviewer_ids.split(",")]
            except ValueError:
                return "reviewer_ids 格式錯誤，請使用逗號分隔的數字（如 1,2,3）"

        client = get_client()
        mr = client.create_merge_request(
            project_id, source_branch, target_branch, title,
            description=description, assignee_id=assignee_id,
            reviewer_ids=parsed_reviewer_ids
        )
        return f"✓ MR 已建立: !{mr['iid']} — {mr['title']}\n網址: {mr.get('web_url', '')}"
    except GitLabAPIError as e:
        return f"建立 MR 失敗: {str(e)}"


@mcp.tool()
def update_merge_request(project_id: int | str, mr_iid: int,
                         title: str = None, description: str = None,
                         state_event: str = None, assignee_id: int = None,
                         reviewer_ids: str = None, target_branch: str = None) -> str:
    """更新 Merge Request

    Args:
        project_id: 專案 ID 或路徑
        mr_iid: MR 的 IID
        title: 新標題
        description: 新描述
        state_event: 狀態變更（close 或 reopen）
        assignee_id: 新指派人 ID
        reviewer_ids: 審核者 ID 列表（逗號分隔）
        target_branch: 新目標分支
    """
    try:
        data = {}
        if title is not None:
            data["title"] = title
        if description is not None:
            data["description"] = description
        if state_event is not None:
            data["state_event"] = state_event
        if assignee_id is not None:
            data["assignee_id"] = assignee_id
        if target_branch is not None:
            data["target_branch"] = target_branch
        if reviewer_ids is not None:
            try:
                data["reviewer_ids"] = [int(x.strip()) for x in reviewer_ids.split(",")]
            except ValueError:
                return "reviewer_ids 格式錯誤"

        if not data:
            return "請至少提供一個要更新的欄位"

        v = GitLabValidator.validate_merge_request_data(data, is_update=True)
        if not v.is_valid:
            return "驗證失敗：\n" + "\n".join(v.errors)

        client = get_client()
        mr = client.update_merge_request(project_id, mr_iid, **data)
        return f"✓ MR !{mr['iid']} 已更新 — {mr['title']} [{mr.get('state', '')}]"
    except GitLabAPIError as e:
        return f"更新 MR 失敗: {str(e)}"


@mcp.tool()
def merge_merge_request(project_id: int | str, mr_iid: int,
                        merge_commit_message: str = None,
                        should_remove_source_branch: bool = False) -> str:
    """合併 Merge Request

    Args:
        project_id: 專案 ID 或路徑
        mr_iid: MR 的 IID
        merge_commit_message: 自訂合併 commit 訊息
        should_remove_source_branch: 合併後是否刪除來源分支
    """
    try:
        client = get_client()
        mr = client.merge_merge_request(
            project_id, mr_iid,
            merge_commit_message=merge_commit_message,
            should_remove_source_branch=should_remove_source_branch
        )
        result = f"✓ MR !{mr['iid']} 已合併 — {mr['title']}"
        if should_remove_source_branch:
            result += f"\n來源分支 {mr.get('source_branch', '')} 已標記刪除"
        return result
    except GitLabAPIError as e:
        return f"合併 MR 失敗: {str(e)}"


@mcp.tool()
def approve_merge_request(project_id: int | str, mr_iid: int) -> str:
    """核准 Merge Request

    Args:
        project_id: 專案 ID 或路徑
        mr_iid: MR 的 IID
    """
    try:
        client = get_client()
        client.approve_merge_request(project_id, mr_iid)
        return f"✓ MR !{mr_iid} 已核准"
    except GitLabAPIError as e:
        return f"核准 MR 失敗: {str(e)}"


@mcp.tool()
def get_merge_request_changes(project_id: int | str, mr_iid: int) -> str:
    """取得 Merge Request 的檔案變更（diff）

    Args:
        project_id: 專案 ID 或路徑
        mr_iid: MR 的 IID
    """
    try:
        client = get_client()
        data = client.get_merge_request_changes(project_id, mr_iid)

        changes = data.get("changes", [])
        if not changes:
            return "此 MR 沒有檔案變更"

        lines = [f"MR !{mr_iid} 共有 {len(changes)} 個檔案變更：\n"]
        for c in changes:
            old_path = c.get("old_path", "")
            new_path = c.get("new_path", "")

            if c.get("new_file"):
                status = "新增"
            elif c.get("deleted_file"):
                status = "刪除"
            elif c.get("renamed_file"):
                status = f"重新命名: {old_path} → {new_path}"
            else:
                status = "修改"

            lines.append(f"  [{status}] {new_path}")

            diff = c.get("diff", "")
            if diff:
                # 截斷過長的 diff
                if len(diff) > 2000:
                    diff = diff[:2000] + "\n... (diff 已截斷)"
                lines.append(f"```diff\n{diff}\n```\n")

        return "\n".join(lines)
    except GitLabAPIError as e:
        return f"取得 MR 變更失敗: {str(e)}"


@mcp.tool()
def get_merge_request_commits(project_id: int | str, mr_iid: int) -> str:
    """取得 Merge Request 包含的 commits

    Args:
        project_id: 專案 ID 或路徑
        mr_iid: MR 的 IID
    """
    try:
        client = get_client()
        commits = client.get_merge_request_commits(project_id, mr_iid)

        if not commits:
            return "此 MR 沒有 commits"

        lines = [f"MR !{mr_iid} 包含 {len(commits)} 個 commits：\n"]
        for c in commits:
            lines.append(
                f"- {c.get('short_id', 'N/A')} {c.get('title', 'N/A')}"
                f"\n  作者: {c.get('author_name', 'N/A')} | {c.get('authored_date', 'N/A')}"
            )
        return "\n".join(lines)
    except GitLabAPIError as e:
        return f"取得 MR commits 失敗: {str(e)}"


@mcp.tool()
def list_merge_request_notes(project_id: int | str, mr_iid: int,
                             page: int = 1, per_page: int = 20) -> str:
    """列出 Merge Request 的留言

    Args:
        project_id: 專案 ID 或路徑
        mr_iid: MR 的 IID
        page: 頁碼
        per_page: 每頁筆數
    """
    try:
        client = get_client()
        notes = client.list_merge_request_notes(project_id, mr_iid, page=page, per_page=per_page)

        if not notes:
            return "此 MR 沒有留言"

        lines = [f"MR !{mr_iid} 的留言（共 {len(notes)} 則）：\n"]
        for n in notes:
            system_tag = " [系統]" if n.get("system") else ""
            lines.append(
                f"📝 #{n['id']}{system_tag}"
                f"\n  作者: {n.get('author', {}).get('name', 'N/A')}"
                f"\n  時間: {n.get('created_at', 'N/A')}"
                f"\n  內容: {n.get('body', '')}\n"
            )
        return "\n".join(lines)
    except GitLabAPIError as e:
        return f"列出 MR 留言失敗: {str(e)}"


@mcp.tool()
def create_merge_request_note(project_id: int | str, mr_iid: int,
                              body: str) -> str:
    """新增 Merge Request 留言

    Args:
        project_id: 專案 ID 或路徑
        mr_iid: MR 的 IID
        body: 留言內容（支援 Markdown）
    """
    try:
        if not body or not body.strip():
            return "留言內容不能為空"

        client = get_client()
        note = client.create_merge_request_note(project_id, mr_iid, body)
        return f"✓ 留言已新增至 MR !{mr_iid}（留言 ID: {note['id']}）"
    except GitLabAPIError as e:
        return f"新增留言失敗: {str(e)}"


# ======================================================================
# CI/CD Pipeline 與 Job 工具
# ======================================================================


@mcp.tool()
def list_pipelines(project_id: int | str, status: str = None,
                   ref: str = None, page: int = 1, per_page: int = 20) -> str:
    """列出專案的 CI/CD Pipelines

    Args:
        project_id: 專案 ID 或路徑
        status: 狀態篩選（running, pending, success, failed, canceled, skipped）
        ref: 分支或標籤名稱篩選
        page: 頁碼
        per_page: 每頁筆數
    """
    try:
        if status:
            v = GitLabValidator.validate_pipeline_status(status)
            if not v.is_valid:
                return "\n".join(v.errors)

        client = get_client()
        pipelines = client.list_pipelines(project_id, status=status, ref=ref,
                                          page=page, per_page=per_page)
        if not pipelines:
            return "找不到符合條件的 Pipeline"

        status_emoji = {
            "success": "✅", "failed": "❌", "running": "🔄",
            "pending": "⏳", "canceled": "⛔", "skipped": "⏭️",
            "created": "🆕", "manual": "👋"
        }
        lines = [f"找到 {len(pipelines)} 個 Pipeline：\n"]
        for p in pipelines:
            emoji = status_emoji.get(p.get("status", ""), "⚪")
            lines.append(
                f"{emoji} #{p['id']} [{p.get('status', '')}] ref: {p.get('ref', 'N/A')}"
                f"\n  SHA: {p.get('sha', 'N/A')[:8]} | {p.get('web_url', '')}\n"
            )
        return "\n".join(lines)
    except GitLabAPIError as e:
        return f"列出 Pipeline 失敗: {str(e)}"


@mcp.tool()
def get_pipeline(project_id: int | str, pipeline_id: int) -> str:
    """取得 Pipeline 詳細資訊

    Args:
        project_id: 專案 ID 或路徑
        pipeline_id: Pipeline ID
    """
    try:
        client = get_client()
        p = client.get_pipeline(project_id, pipeline_id)

        status_emoji = {
            "success": "✅", "failed": "❌", "running": "🔄",
            "pending": "⏳", "canceled": "⛔", "skipped": "⏭️"
        }
        emoji = status_emoji.get(p.get("status", ""), "⚪")

        return f"""{emoji} Pipeline #{p['id']}
狀態: {p.get('status', 'N/A')}
Ref: {p.get('ref', 'N/A')}
SHA: {p.get('sha', 'N/A')}
建立時間: {p.get('created_at', 'N/A')}
更新時間: {p.get('updated_at', 'N/A')}
開始時間: {p.get('started_at', 'N/A')}
完成時間: {p.get('finished_at', 'N/A')}
持續時間: {p.get('duration', 'N/A')}秒
網址: {p.get('web_url', '')}"""
    except GitLabAPIError as e:
        return f"取得 Pipeline 失敗: {str(e)}"


@mcp.tool()
def create_pipeline(project_id: int | str, ref: str,
                    variables: str = None) -> str:
    """觸發新的 CI/CD Pipeline

    Args:
        project_id: 專案 ID 或路徑
        ref: 分支名稱或標籤
        variables: Pipeline 變數（JSON 格式，如 '[{"key":"VAR1","value":"val1"}]'）
    """
    try:
        parsed_vars = None
        if variables:
            try:
                parsed_vars = json.loads(variables)
            except json.JSONDecodeError:
                return "variables 格式錯誤，請使用 JSON 格式：[{\"key\":\"KEY\",\"value\":\"VALUE\"}]"

            v = GitLabValidator.validate_pipeline_data({"ref": ref, "variables": parsed_vars})
            if not v.is_valid:
                return "驗證失敗：\n" + "\n".join(v.errors)

        client = get_client()
        p = client.create_pipeline(project_id, ref, variables=parsed_vars)
        return f"✓ Pipeline #{p['id']} 已觸發\n  Ref: {ref} | 狀態: {p.get('status', 'N/A')}\n  網址: {p.get('web_url', '')}"
    except GitLabAPIError as e:
        return f"觸發 Pipeline 失敗: {str(e)}"


@mcp.tool()
def retry_pipeline(project_id: int | str, pipeline_id: int) -> str:
    """重試 Pipeline

    Args:
        project_id: 專案 ID 或路徑
        pipeline_id: Pipeline ID
    """
    try:
        client = get_client()
        p = client.retry_pipeline(project_id, pipeline_id)
        return f"✓ Pipeline #{p['id']} 已重試 | 狀態: {p.get('status', 'N/A')}"
    except GitLabAPIError as e:
        return f"重試 Pipeline 失敗: {str(e)}"


@mcp.tool()
def cancel_pipeline(project_id: int | str, pipeline_id: int) -> str:
    """取消 Pipeline

    Args:
        project_id: 專案 ID 或路徑
        pipeline_id: Pipeline ID
    """
    try:
        client = get_client()
        p = client.cancel_pipeline(project_id, pipeline_id)
        return f"✓ Pipeline #{p['id']} 已取消 | 狀態: {p.get('status', 'N/A')}"
    except GitLabAPIError as e:
        return f"取消 Pipeline 失敗: {str(e)}"


@mcp.tool()
def list_pipeline_jobs(project_id: int | str, pipeline_id: int,
                       page: int = 1, per_page: int = 20) -> str:
    """列出 Pipeline 的所有 Jobs

    Args:
        project_id: 專案 ID 或路徑
        pipeline_id: Pipeline ID
        page: 頁碼
        per_page: 每頁筆數
    """
    try:
        client = get_client()
        jobs = client.list_pipeline_jobs(project_id, pipeline_id, page=page, per_page=per_page)

        if not jobs:
            return "此 Pipeline 沒有 Jobs"

        status_emoji = {
            "success": "✅", "failed": "❌", "running": "🔄",
            "pending": "⏳", "canceled": "⛔", "skipped": "⏭️",
            "created": "🆕", "manual": "👋"
        }
        lines = [f"Pipeline #{pipeline_id} 的 Jobs（共 {len(jobs)} 個）：\n"]
        for j in jobs:
            emoji = status_emoji.get(j.get("status", ""), "⚪")
            duration = f"{j['duration']:.1f}秒" if j.get("duration") else "N/A"
            lines.append(
                f"{emoji} [{j.get('stage', 'N/A')}] {j['name']} (#{j['id']})"
                f"\n  狀態: {j.get('status', 'N/A')} | 持續時間: {duration} | {j.get('web_url', '')}\n"
            )
        return "\n".join(lines)
    except GitLabAPIError as e:
        return f"列出 Jobs 失敗: {str(e)}"


@mcp.tool()
def get_job(project_id: int | str, job_id: int) -> str:
    """取得 Job 詳細資訊

    Args:
        project_id: 專案 ID 或路徑
        job_id: Job ID
    """
    try:
        client = get_client()
        j = client.get_job(project_id, job_id)

        status_emoji = {
            "success": "✅", "failed": "❌", "running": "🔄",
            "pending": "⏳", "canceled": "⛔", "skipped": "⏭️"
        }
        emoji = status_emoji.get(j.get("status", ""), "⚪")
        duration = f"{j['duration']:.1f}秒" if j.get("duration") else "N/A"

        return f"""{emoji} Job #{j['id']} — {j.get('name', 'N/A')}
階段: {j.get('stage', 'N/A')}
狀態: {j.get('status', 'N/A')}
持續時間: {duration}
Ref: {j.get('ref', 'N/A')}
Runner: {j.get('runner', {}).get('description', 'N/A') if j.get('runner') else 'N/A'}
建立時間: {j.get('created_at', 'N/A')}
開始時間: {j.get('started_at', 'N/A')}
完成時間: {j.get('finished_at', 'N/A')}
網址: {j.get('web_url', '')}

💡 使用 get_job_log({j['id']}) 查看執行日誌"""
    except GitLabAPIError as e:
        return f"取得 Job 失敗: {str(e)}"


@mcp.tool()
def get_job_log(project_id: int | str, job_id: int, last_lines: int = 0) -> str:
    """取得 Job 的執行日誌

    Args:
        project_id: 專案 ID 或路徑
        job_id: Job ID
        last_lines: 只顯示最後 N 行（0 表示全部，預設 0）
    """
    try:
        client = get_client()
        log = client.get_job_log(project_id, job_id)

        if not log:
            return f"Job #{job_id} 沒有日誌"

        if last_lines > 0:
            log_lines = log.splitlines()
            if len(log_lines) > last_lines:
                log = "\n".join(log_lines[-last_lines:])
                return f"Job #{job_id} 日誌（最後 {last_lines} 行，共 {len(log_lines)} 行）：\n\n{log}"

        # 截斷過長的日誌
        if len(log) > 50000:
            log = log[:50000] + "\n\n... (日誌已截斷，共 " + str(len(log)) + " 字元，請使用 last_lines 參數限制輸出)"

        return f"Job #{job_id} 日誌：\n\n{log}"
    except GitLabAPIError as e:
        return f"取得日誌失敗: {str(e)}"


@mcp.tool()
def retry_job(project_id: int | str, job_id: int) -> str:
    """重試單一 Job

    Args:
        project_id: 專案 ID 或路徑
        job_id: Job ID
    """
    try:
        client = get_client()
        j = client.retry_job(project_id, job_id)
        return f"✓ Job #{j['id']} ({j.get('name', 'N/A')}) 已重試 | 狀態: {j.get('status', 'N/A')}"
    except GitLabAPIError as e:
        return f"重試 Job 失敗: {str(e)}"


# ======================================================================
# Repository 工具
# ======================================================================


@mcp.tool()
def list_branches(project_id: int | str, search: str = None,
                  page: int = 1, per_page: int = 20) -> str:
    """列出專案的分支

    Args:
        project_id: 專案 ID 或路徑
        search: 搜尋關鍵字
        page: 頁碼
        per_page: 每頁筆數
    """
    try:
        client = get_client()
        branches = client.list_branches(project_id, search=search, page=page, per_page=per_page)

        if not branches:
            return "找不到符合條件的分支"

        lines = [f"找到 {len(branches)} 個分支：\n"]
        for b in branches:
            flags = []
            if b.get("default"):
                flags.append("預設")
            if b.get("protected"):
                flags.append("受保護")
            if b.get("merged"):
                flags.append("已合併")
            flag_str = f" ({', '.join(flags)})" if flags else ""

            commit = b.get("commit", {})
            lines.append(
                f"- {b['name']}{flag_str}"
                f"\n  最新 commit: {commit.get('short_id', 'N/A')} {commit.get('title', 'N/A')}"
            )
        return "\n".join(lines)
    except GitLabAPIError as e:
        return f"列出分支失敗: {str(e)}"


@mcp.tool()
def get_branch(project_id: int | str, branch_name: str) -> str:
    """取得分支詳細資訊

    Args:
        project_id: 專案 ID 或路徑
        branch_name: 分支名稱
    """
    try:
        client = get_client()
        b = client.get_branch(project_id, branch_name)

        commit = b.get("commit", {})
        flags = []
        if b.get("default"):
            flags.append("預設")
        if b.get("protected"):
            flags.append("受保護")
        if b.get("merged"):
            flags.append("已合併")

        return f"""分支: {b['name']}
屬性: {', '.join(flags) if flags else '無'}
最新 Commit: {commit.get('id', 'N/A')}
Commit 標題: {commit.get('title', 'N/A')}
Commit 作者: {commit.get('author_name', 'N/A')}
Commit 時間: {commit.get('committed_date', 'N/A')}
網址: {b.get('web_url', '')}"""
    except GitLabAPIError as e:
        return f"取得分支失敗: {str(e)}"


@mcp.tool()
def list_commits(project_id: int | str, ref_name: str = None,
                 path: str = None, page: int = 1, per_page: int = 20) -> str:
    """列出 Commits

    Args:
        project_id: 專案 ID 或路徑
        ref_name: 分支或標籤名稱（預設為預設分支）
        path: 檔案路徑篩選
        page: 頁碼
        per_page: 每頁筆數
    """
    try:
        client = get_client()
        commits = client.list_commits(project_id, ref_name=ref_name, path=path,
                                       page=page, per_page=per_page)
        if not commits:
            return "找不到符合條件的 commits"

        lines = [f"找到 {len(commits)} 個 commits：\n"]
        for c in commits:
            lines.append(
                f"- {c.get('short_id', 'N/A')} {c.get('title', 'N/A')}"
                f"\n  作者: {c.get('author_name', 'N/A')} | {c.get('authored_date', 'N/A')}"
            )
        return "\n".join(lines)
    except GitLabAPIError as e:
        return f"列出 commits 失敗: {str(e)}"


@mcp.tool()
def get_commit(project_id: int | str, sha: str) -> str:
    """取得 Commit 詳細資訊

    Args:
        project_id: 專案 ID 或路徑
        sha: Commit SHA（完整或縮短）
    """
    try:
        client = get_client()
        c = client.get_commit(project_id, sha)

        stats = c.get("stats", {})
        return f"""Commit {c.get('id', 'N/A')}
標題: {c.get('title', 'N/A')}
訊息: {c.get('message', 'N/A')}
作者: {c.get('author_name', 'N/A')} <{c.get('author_email', '')}>
時間: {c.get('authored_date', 'N/A')}
新增: {stats.get('additions', 0)} 行 | 刪除: {stats.get('deletions', 0)} 行 | 變更檔案: {stats.get('total', 0)}
網址: {c.get('web_url', '')}"""
    except GitLabAPIError as e:
        return f"取得 commit 失敗: {str(e)}"


@mcp.tool()
def compare_branches(project_id: int | str, from_ref: str, to_ref: str) -> str:
    """比較兩個分支或 commit 的差異

    Args:
        project_id: 專案 ID 或路徑
        from_ref: 起始分支/commit
        to_ref: 目標分支/commit
    """
    try:
        client = get_client()
        data = client.compare_branches(project_id, from_ref, to_ref)

        commits = data.get("commits", [])
        diffs = data.get("diffs", [])

        lines = [f"比較 {from_ref} → {to_ref}："]
        lines.append(f"Commits: {len(commits)} 個 | 檔案變更: {len(diffs)} 個\n")

        if commits:
            lines.append("--- Commits ---")
            for c in commits[:20]:  # 限制最多顯示 20 個 commits
                lines.append(f"- {c.get('short_id', 'N/A')} {c.get('title', 'N/A')}")
            if len(commits) > 20:
                lines.append(f"... 還有 {len(commits) - 20} 個 commits")

        if diffs:
            lines.append("\n--- 檔案變更 ---")
            for d in diffs:
                new_path = d.get("new_path", "")
                if d.get("new_file"):
                    lines.append(f"  [新增] {new_path}")
                elif d.get("deleted_file"):
                    lines.append(f"  [刪除] {new_path}")
                elif d.get("renamed_file"):
                    lines.append(f"  [重新命名] {d.get('old_path', '')} → {new_path}")
                else:
                    lines.append(f"  [修改] {new_path}")

        return "\n".join(lines)
    except GitLabAPIError as e:
        return f"比較分支失敗: {str(e)}"


@mcp.tool()
def list_repository_tree(project_id: int | str, path: str = "",
                         ref: str = None, recursive: bool = False) -> str:
    """瀏覽 Repository 檔案結構

    Args:
        project_id: 專案 ID 或路徑
        path: 目錄路徑（預設為根目錄）
        ref: 分支或標籤（預設為預設分支）
        recursive: 是否遞迴列出子目錄
    """
    try:
        client = get_client()
        items = client.list_repository_tree(project_id, path=path, ref=ref,
                                             recursive=recursive, per_page=100)
        if not items:
            return "此路徑下沒有檔案"

        path_display = path or "/"
        lines = [f"Repository 檔案結構（{path_display}）：\n"]

        # 排序：目錄在前，檔案在後
        dirs = [i for i in items if i.get("type") == "tree"]
        files = [i for i in items if i.get("type") == "blob"]

        for d in dirs:
            lines.append(f"📁 {d['name']}/")
        for f in files:
            lines.append(f"📄 {f['name']}")

        return "\n".join(lines)
    except GitLabAPIError as e:
        return f"瀏覽檔案結構失敗: {str(e)}"


# ======================================================================
# 主入口點
# ======================================================================


def main():
    """MCP 服務器主入口點"""
    parser = argparse.ArgumentParser(
        description='GitLab MCP 服務器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
範例:
  gitlab-mcp                           # 預設 stdio 模式
  gitlab-mcp --transport sse           # SSE 模式（預設 port 8000）
  gitlab-mcp --transport sse --port 3000 --host 127.0.0.1
        '''
    )
    parser.add_argument(
        '--transport', '-t',
        choices=['stdio', 'sse'],
        default=None,
        help='傳輸模式：stdio（預設）或 sse'
    )
    parser.add_argument(
        '--host', '-H',
        default=None,
        help='SSE 模式綁定位址（預設: 0.0.0.0）'
    )
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=None,
        help='SSE 模式監聽埠（預設: 8000）'
    )

    args = parser.parse_args()
    config = get_config()

    # 命令列參數優先於環境變數
    transport = args.transport or config.transport

    if transport == 'sse':
        host = args.host or config.sse_host
        port = args.port or config.sse_port
        mcp.settings.host = host
        mcp.settings.port = port
        print(f"啟動 SSE 模式: http://{host}:{port}", flush=True)
        mcp.run('sse')
    else:
        mcp.run('stdio')


if __name__ == "__main__":
    main()
