import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.user import AdminUserUpdate, ChangePasswordRequest, UserResponse, UserUpdate
from app.services import audit_service, auth_service

router = APIRouter(prefix="/users", tags=["users"])


# ---------------------------------------------------------------------------
# Self-service endpoints (any authenticated user)
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_me(
    body: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    if body.first_name is not None:
        current_user.first_name = body.first_name
    if body.last_name is not None:
        current_user.last_name = body.last_name
    if body.email_opt_in is not None:
        current_user.email_opt_in = body.email_opt_in
    if body.in_app_opt_in is not None:
        current_user.in_app_opt_in = body.in_app_opt_in
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.put("/me/password", response_model=MessageResponse)
async def change_my_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    try:
        await auth_service.change_password(db, current_user, body.current_password, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return MessageResponse(message="Password updated successfully")


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=PaginatedResponse[UserResponse])
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: str | None = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    base = select(User).where(User.deleted_at.is_(None))
    count_q = select(func.count(User.id)).where(User.deleted_at.is_(None))
    if role:
        base = base.where(User.role == role)
        count_q = count_q.where(User.role == role)

    total: int = (await db.execute(count_q)).scalar_one()
    rows = list(
        (
            await db.execute(
                base.order_by(User.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars()
    )
    pages = (total + page_size - 1) // page_size if total else 0
    return PaginatedResponse(
        items=[UserResponse.model_validate(u) for u in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> User:
    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: AdminUserUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> User:
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify your own account")

    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    changed: dict = {}
    if body.role is not None and body.role != user.role:
        changed["old_role"] = user.role
        user.role = body.role
    if body.is_active is not None and body.is_active != user.is_active:
        changed["old_is_active"] = user.is_active
        user.is_active = body.is_active

    if changed:
        await audit_service.log_event(
            db,
            action="user.updated",
            actor_id=admin.id,
            resource_type="user",
            resource_id=user.id,
            event_metadata=changed,
        )

    await db.commit()
    await db.refresh(user)
    return user
