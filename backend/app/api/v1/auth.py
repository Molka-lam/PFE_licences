from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshResponse,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from app.schemas.common import MessageResponse
from app.schemas.user import UserResponse
from app.services import auth_service

_COOKIE_NAME = "refresh_token"
_COOKIE_PATH = "/api/v1/auth"
_REFRESH_TTL = 7 * 24 * 60 * 60  # 7 days in seconds

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        path=_COOKIE_PATH,
        max_age=_REFRESH_TTL,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> User:
    try:
        user = await auth_service.register_user(
            db, body.email, body.password, body.first_name, body.last_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    try:
        access_token, refresh_token_raw = await auth_service.login_user(
            db,
            body.email,
            body.password,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    _set_refresh_cookie(response, refresh_token_raw)
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> RefreshResponse:
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")
    try:
        new_access, new_refresh_raw = await auth_service.refresh_tokens(db, refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    _set_refresh_cookie(response, new_refresh_raw)
    return RefreshResponse(access_token=new_access)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    if refresh_token:
        await auth_service.logout_user(
            db,
            refresh_token,
            current_user.id,
            ip_address=request.client.host if request.client else None,
        )
    response.delete_cookie(key=_COOKIE_NAME, path=_COOKIE_PATH)
    return MessageResponse(message="Logged out successfully")


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(body: VerifyEmailRequest, db: AsyncSession = Depends(get_db)) -> MessageResponse:
    try:
        await auth_service.verify_email(db, body.token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return MessageResponse(message="Email verified successfully")


@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    await auth_service.forgot_password(db, body.email)
    return MessageResponse(message="If that email exists, a reset link has been sent")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)) -> MessageResponse:
    try:
        await auth_service.reset_password(db, body.token, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return MessageResponse(message="Password reset successfully")
