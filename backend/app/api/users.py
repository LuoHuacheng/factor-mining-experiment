"""用户信息管理 API 路由 —— 更新个人信息、修改密码"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password, verify_password
from app.core.deps import get_current_user, get_session
from app.models.user import User
from app.schemas.auth import UserInfoResponse
from app.schemas.user import ChangePasswordRequest, UpdateUserRequest

router = APIRouter(prefix="/api/users", tags=["用户管理"])


@router.put("/me", response_model=UserInfoResponse)
async def update_user_info(
    body: UpdateUserRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserInfoResponse:
    """更新当前用户的基本信息（手机号、邮箱、头像）"""
    from sqlalchemy import select

    # 检查手机号唯一性
    if body.phone is not None and body.phone != current_user.phone:
        stmt = select(User).where(User.phone == body.phone)
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="手机号已被其他用户使用",
            )
        current_user.phone = body.phone

    # 检查邮箱唯一性
    if body.email is not None and body.email != current_user.email:
        stmt = select(User).where(User.email == body.email)
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="邮箱已被其他用户使用",
            )
        current_user.email = body.email

    if body.avatar is not None:
        current_user.avatar = body.avatar

    await session.commit()
    await session.refresh(current_user)
    return UserInfoResponse.model_validate(current_user)


@router.put("/me/password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """修改当前用户密码"""
    if not verify_password(body.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码不正确",
        )

    current_user.hashed_password = hash_password(body.new_password)
    await session.commit()
    return {"message": "密码修改成功"}


@router.get("/me/notify-settings")
async def get_notify_settings(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """读取当前用户通知开关（首次读取自动建默认行）"""
    from app.services.notify.notify_svc import ensure_notify_setting

    setting = await ensure_notify_setting(session, current_user.id)
    await session.commit()
    return {
        "notify_trade": bool(setting.notify_trade),
        "notify_fund": bool(setting.notify_fund),
        "notify_price_alert": bool(setting.notify_price_alert),
        "notify_sound_enabled": bool(setting.notify_sound_enabled),
    }


@router.put("/me/notify-settings")
async def update_notify_settings(
    body: dict,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """更新当前用户通知开关（含提示音，可选）"""
    from app.services.notify.notify_svc import ensure_notify_setting

    setting = await ensure_notify_setting(session, current_user.id)
    for field in (
        "notify_trade",
        "notify_fund",
        "notify_price_alert",
        "notify_sound_enabled",
    ):
        val = body.get(field)
        if isinstance(val, bool):
            setattr(setting, field, val)
    await session.commit()
    return {
        "notify_trade": bool(setting.notify_trade),
        "notify_fund": bool(setting.notify_fund),
        "notify_price_alert": bool(setting.notify_price_alert),
        "notify_sound_enabled": bool(setting.notify_sound_enabled),
    }
