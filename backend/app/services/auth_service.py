import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import hash_password, verify_password
from app.core.jwt import create_access_token, create_refresh_token
from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.models.audit_log import AuditLog
from app.config import settings


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def register_user(db: AsyncSession, email: str, password: str, first_name: str | None, last_name: str | None) -> User:
    # Check email not already taken
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none() is not None:
        raise ValueError("Email already registered")

    user = User(
        email=email,
        hashed_password=hash_password(password),
        first_name=first_name,
        last_name=last_name,
        role="client",
        email_verify_token=secrets.token_urlsafe(32),
        email_verify_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    # NOTE: In Phase 5, send verification email here
    return user


async def login_user(
    db: AsyncSession,
    email: str,
    password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, str]:  # (access_token, refresh_token_raw)
    result = await db.execute(select(User).where(User.email == email, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password):
        raise ValueError("Invalid credentials")
    if not user.is_active:
        raise ValueError("Account is disabled")

    # Create tokens
    access_token = create_access_token(str(user.id), user.role)
    refresh_token_raw = create_refresh_token(str(user.id))

    # Store refresh token hash
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    rt = RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(refresh_token_raw),
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=expires_at,
    )
    db.add(rt)

    # Audit log
    db.add(AuditLog(
        actor_id=user.id,
        action="auth.login",
        ip_address=ip_address,
        user_agent=user_agent,
    ))
    await db.commit()
    return access_token, refresh_token_raw


async def refresh_tokens(
    db: AsyncSession,
    refresh_token_raw: str,
) -> tuple[str, str]:  # (new_access_token, new_refresh_token_raw)
    from app.core.jwt import decode_refresh_token, JWTError
    try:
        payload = decode_refresh_token(refresh_token_raw)
    except JWTError:
        raise ValueError("Invalid or expired refresh token")

    user_id = payload["sub"]
    token_hash = _hash_token(refresh_token_raw)

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked.is_(False),
        )
    )
    rt = result.scalar_one_or_none()
    if rt is None:
        raise ValueError("Refresh token not found or already revoked")

    # Revoke old token
    rt.revoked = True
    rt.revoked_at = datetime.now(timezone.utc)

    # Get user
    user_result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise ValueError("User not found or disabled")

    # Issue new tokens
    new_access = create_access_token(str(user.id), user.role)
    new_refresh_raw = create_refresh_token(str(user.id))

    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    new_rt = RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(new_refresh_raw),
        ip_address=rt.ip_address,
        user_agent=rt.user_agent,
        expires_at=expires_at,
    )
    db.add(new_rt)
    await db.commit()
    return new_access, new_refresh_raw


async def logout_user(db: AsyncSession, refresh_token_raw: str, user_id: uuid.UUID, ip_address: str | None = None) -> None:
    token_hash = _hash_token(refresh_token_raw)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked.is_(False),
        )
    )
    rt = result.scalar_one_or_none()
    if rt is not None:
        rt.revoked = True
        rt.revoked_at = datetime.now(timezone.utc)

    db.add(AuditLog(actor_id=user_id, action="auth.logout", ip_address=ip_address))
    await db.commit()


async def verify_email(db: AsyncSession, token: str) -> None:
    result = await db.execute(
        select(User).where(
            User.email_verify_token == token,
            User.email_verified.is_(False),
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("Invalid or expired verification token")
    if user.email_verify_token_expires_at and user.email_verify_token_expires_at < datetime.now(timezone.utc):
        raise ValueError("Verification token expired")

    user.email_verified = True
    user.email_verify_token = None
    user.email_verify_token_expires_at = None
    await db.commit()


async def forgot_password(db: AsyncSession, email: str) -> None:
    result = await db.execute(select(User).where(User.email == email, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if user is None:
        return  # Silently succeed to prevent email enumeration

    user.password_reset_token = secrets.token_urlsafe(32)
    user.password_reset_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await db.commit()
    # NOTE: In Phase 5, send reset email here


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    result = await db.execute(
        select(User).where(User.password_reset_token == token)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("Invalid or expired reset token")
    if user.password_reset_token_expires_at and user.password_reset_token_expires_at < datetime.now(timezone.utc):
        raise ValueError("Reset token expired")

    user.hashed_password = hash_password(new_password)
    user.password_reset_token = None
    user.password_reset_token_expires_at = None
    db.add(AuditLog(actor_id=user.id, action="auth.password_reset"))
    await db.commit()


async def change_password(db: AsyncSession, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.hashed_password):
        raise ValueError("Current password is incorrect")
    user.hashed_password = hash_password(new_password)
    await db.commit()
