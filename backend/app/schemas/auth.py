"""认证相关的 Pydantic schema —— 请求/响应数据结构"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ============ 请求 Schema ============


class RegisterRequest(BaseModel):
    """注册请求体"""

    username: Annotated[str, Field(min_length=3, max_length=50, description="用户名")]
    password: Annotated[str, Field(min_length=6, max_length=100, description="密码")]
    phone: Annotated[str | None, Field(max_length=20, description="手机号")] = None
    email: Annotated[str | None, Field(max_length=100, description="邮箱")] = None
    trading_mode: Annotated[
        str,
        Field(default="live", description="注册后首登模式 live/virtual"),
    ] = "live"

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, value: str) -> str:
        """用户名只允许字母、数字、下划线"""
        if not value.replace("_", "").isalnum():
            raise ValueError("用户名只能包含字母、数字和下划线")
        return value

    @field_validator("email")
    @classmethod
    def email_format(cls, value: str | None) -> str | None:
        """简单校验邮箱格式"""
        if value is not None and "@" not in value:
            raise ValueError("邮箱格式不正确")
        return value


class LoginRequest(BaseModel):
    """登录请求体"""

    username: Annotated[str, Field(description="用户名")]
    password: Annotated[str, Field(description="密码")]
    # live=实盘数据；virtual=虚拟盘 openctp 7×24；会话内不可切换
    trading_mode: Annotated[
        str,
        Field(default="live", description="live / virtual"),
    ] = "live"


class RefreshRequest(BaseModel):
    """刷新 token 请求体"""

    refresh_token: Annotated[str, Field(description="refresh token")]
    # 可选：若不传则沿用 refresh JWT 内绑定的 mode
    trading_mode: Annotated[str | None, Field(default=None)] = None


# ============ 响应 Schema ============


class TokenResponse(BaseModel):
    """token 响应体"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserInfoResponse(BaseModel):
    """用户信息响应体"""

    id: UUID
    username: str
    phone: str | None
    email: str | None
    avatar: str | None
    real_name_verified: bool
    role: str
    status: str
    created_at: datetime
    updated_at: datetime
    # 当前会话交易盘（来自 JWT，非用户表字段）
    trading_mode: str = "live"

    model_config = {"from_attributes": True}
