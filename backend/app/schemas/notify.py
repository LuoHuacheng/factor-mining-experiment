"""通知 / 价格预警 / 通知开关 Pydantic schema"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field


class NotificationItem(BaseModel):
    """通知响应（对齐前端 Message 结构）"""

    id: UUID
    category: str
    title: str
    content: str
    read: bool
    created_at: datetime
    trading_mode: str

    model_config = {"from_attributes": True}


class UnreadCountResponse(BaseModel):
    """未读条数"""

    unread: int


class PriceAlertCreate(BaseModel):
    """新建价格预警"""

    symbol: Annotated[str, Field(min_length=1, max_length=20)]
    contract_name: Annotated[str, Field(min_length=1, max_length=50)]
    direction: Annotated[str, Field(pattern="^(above|below)$")]
    target_price: Annotated[Decimal, Field(gt=0)]


class PriceAlertUpdate(BaseModel):
    """启停预警"""

    enabled: bool


class PriceAlertItem(BaseModel):
    """预警响应"""

    id: UUID
    symbol: str
    contract_name: str
    direction: str
    target_price: float
    enabled: bool
    triggered_at: datetime | None
    created_at: datetime
    trading_mode: str

    model_config = {"from_attributes": True}


class NotifySettingResponse(BaseModel):
    """通知开关响应"""

    notify_trade: bool
    notify_fund: bool
    notify_price_alert: bool
    notify_sound_enabled: bool

    model_config = {"from_attributes": True}


class NotifySettingUpdate(BaseModel):
    """更新通知开关（含提示音，可选）"""

    notify_trade: bool | None = None
    notify_fund: bool | None = None
    notify_price_alert: bool | None = None
    notify_sound_enabled: bool | None = None
