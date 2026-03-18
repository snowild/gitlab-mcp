"""
輸入驗證模組
負責驗證 MCP 工具的輸入參數
"""

from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """驗證結果"""
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class GitLabValidator:
    """GitLab 輸入參數驗證器"""

    # 常數
    MAX_TITLE_LENGTH = 255
    MAX_DESCRIPTION_LENGTH = 1_048_576  # 1MB
    VALID_MR_STATES = {"opened", "closed", "merged", "all"}
    VALID_PIPELINE_STATUSES = {
        "running", "pending", "success", "failed",
        "canceled", "skipped", "created", "manual"
    }
    VALID_MR_STATE_EVENTS = {"close", "reopen"}
    VALID_NOTE_SORT = {"asc", "desc"}

    @classmethod
    def validate_project_id(cls, project_id: int | str) -> ValidationResult:
        """驗證 project_id（支援數字 ID 或路徑格式）"""
        result = ValidationResult()

        if project_id is None:
            result.is_valid = False
            result.errors.append("project_id 為必填參數")
            return result

        if isinstance(project_id, int):
            if project_id <= 0:
                result.is_valid = False
                result.errors.append("project_id 必須大於 0")
        elif isinstance(project_id, str):
            if not project_id.strip():
                result.is_valid = False
                result.errors.append("project_id 不能為空字串")
        else:
            result.is_valid = False
            result.errors.append("project_id 必須是整數或字串")

        return result

    @classmethod
    def validate_merge_request_data(cls, data: dict, is_update: bool = False) -> ValidationResult:
        """驗證 MR 建立/更新資料"""
        result = ValidationResult()

        if not is_update:
            # 建立 MR 時的必填欄位
            for field_name in ["source_branch", "target_branch", "title"]:
                if not data.get(field_name):
                    result.is_valid = False
                    result.errors.append(f"{field_name} 為必填參數")

        # 驗證標題長度
        title = data.get("title")
        if title and len(title) > cls.MAX_TITLE_LENGTH:
            result.is_valid = False
            result.errors.append(f"標題長度不能超過 {cls.MAX_TITLE_LENGTH} 個字元（當前: {len(title)}）")

        # 驗證描述長度
        description = data.get("description")
        if description and len(description) > cls.MAX_DESCRIPTION_LENGTH:
            result.is_valid = False
            result.errors.append(f"描述長度不能超過 {cls.MAX_DESCRIPTION_LENGTH} 個字元")

        # 驗證 state_event
        state_event = data.get("state_event")
        if state_event and state_event not in cls.VALID_MR_STATE_EVENTS:
            result.is_valid = False
            result.errors.append(
                f"state_event 必須是以下值之一: {', '.join(cls.VALID_MR_STATE_EVENTS)}（當前: {state_event}）"
            )

        return result

    @classmethod
    def validate_pipeline_data(cls, data: dict) -> ValidationResult:
        """驗證 Pipeline 觸發資料"""
        result = ValidationResult()

        if not data.get("ref"):
            result.is_valid = False
            result.errors.append("ref 為必填參數（分支名稱或標籤）")

        # 驗證 variables 格式
        variables = data.get("variables")
        if variables is not None:
            if not isinstance(variables, list):
                result.is_valid = False
                result.errors.append("variables 必須是陣列格式")
            else:
                for i, var in enumerate(variables):
                    if not isinstance(var, dict):
                        result.is_valid = False
                        result.errors.append(f"variables[{i}] 必須是物件格式")
                    elif "key" not in var or "value" not in var:
                        result.is_valid = False
                        result.errors.append(f"variables[{i}] 必須包含 key 和 value 欄位")

        return result

    @classmethod
    def validate_mr_state(cls, state: str) -> ValidationResult:
        """驗證 MR 狀態篩選值"""
        result = ValidationResult()
        if state and state not in cls.VALID_MR_STATES:
            result.is_valid = False
            result.errors.append(
                f"state 必須是以下值之一: {', '.join(cls.VALID_MR_STATES)}（當前: {state}）"
            )
        return result

    @classmethod
    def validate_pipeline_status(cls, status: str) -> ValidationResult:
        """驗證 Pipeline 狀態篩選值"""
        result = ValidationResult()
        if status and status not in cls.VALID_PIPELINE_STATUSES:
            result.is_valid = False
            result.errors.append(
                f"status 必須是以下值之一: {', '.join(cls.VALID_PIPELINE_STATUSES)}（當前: {status}）"
            )
        return result

    @classmethod
    def validate_pagination(cls, page: int, per_page: int) -> ValidationResult:
        """驗證分頁參數"""
        result = ValidationResult()
        if page < 1:
            result.is_valid = False
            result.errors.append("page 必須大於 0")
        if per_page < 1 or per_page > 100:
            result.is_valid = False
            result.errors.append("per_page 必須在 1-100 之間")
        return result

    @classmethod
    def get_friendly_error_message(cls, error: Exception, context: str = "") -> str:
        """將技術錯誤轉換為人類友好的訊息"""
        prefix = f"{context}：" if context else ""

        error_str = str(error)

        if "ConnectionError" in type(error).__name__:
            return f"{prefix}無法連接到 GitLab 伺服器，請確認網路連線"
        elif "Timeout" in type(error).__name__:
            return f"{prefix}請求逾時，請稍後再試"
        else:
            return f"{prefix}{error_str}"
