import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.jwt import create_access_token, create_refresh_token, decode_refresh_token
from app.core.security import hash_password, verify_password
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services import audit_service

# Pre-computed bcrypt hash used in login when the email doesn't exist.
# Ensures constant response time, preventing email-enumeration via timing analysis.
_DUMMY_HASH: str = hash_password("__dummy_constant_for_timing__")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _revoke_all_refresh_tokens(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Bulk-revoke all active refresh tokens (called on password change/reset)."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
        .values(revoked=True, revoked_at=datetime.now(timezone.utc))
    )


async def register_user(
    db: AsyncSession,
    email: str,
    password: str,
    first_name: str | None,
    last_name: str | None,
) -> tuple[User, str]:
    """Register a new user. Returns (user, raw_verify_token) — raw token for Phase 5 email delivery."""
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none() is not None:
        raise ValueError("Email already registered")

    raw_verify_token = secrets.token_urlsafe(32)
    user = User(
        email=email,
        hashed_password=hash_password(password),
        first_name=first_name,
        last_name=last_name,
        role="client",
        email_verify_token=_hash_token(raw_verify_token),
        email_verify_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ValueError("Email already registered")
    await db.refresh(user)
    return user, raw_verify_token


async def login_user(
    db: AsyncSession,
    email: str,
    password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, str]:
    result = await db.execute(select(User).where(User.email == email, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()

    if user is None:
        verify_password(password, _DUMMY_HASH)  # constant-time guard — keep bcrypt running
        raise ValueError("Invalid credentials")
    if not verify_password(password, user.hashed_password):
        raise ValueError("Invalid credentials")
    if not user.is_active:
        raise ValueError("Account is disabled")

    access_token = create_access_token(str(user.id), user.role)
    refresh_token_raw = create_refresh_token(str(user.id))

    db.add(RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(refresh_token_raw),
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    await audit_service.log_event(
        db,
        action="auth.login",
        actor_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return access_token, refresh_token_raw


async def refresh_tokens(
    db: AsyncSession,
    refresh_token_raw: str,
) -> tuple[str, str]:
    try:
        payload = decode_refresh_token(refresh_token_raw)
    except JWTError:
        raise ValueError("Invalid or expired refresh token")

    user_id: str = payload["sub"]
    token_hash = _hash_token(refresh_token_raw)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > now,
        )
    )
    rt = result.scalar_one_or_none()
    if rt is None:
        raise ValueError("Refresh token not found or already revoked")

    rt.revoked = True
    rt.revoked_at = now

    user_result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise ValueError("User not found or disabled")

    new_access = create_access_token(str(user.id), user.role)
    new_refresh_raw = create_refresh_token(str(user.id))

    db.add(RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(new_refresh_raw),
        ip_address=rt.ip_address,
        user_agent=rt.user_agent,
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    await db.commit()
    return new_access, new_refresh_raw


async def logout_user(
    db: AsyncSession,
    refresh_token_raw: str,
    user_id: uuid.UUID,
    ip_address: str | None = None,
) -> None:
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

    await audit_service.log_event(db, action="auth.logout", actor_id=user_id, ip_address=ip_address)
    await db.commit()


async def verify_email(db: AsyncSession, token: str) -> None:
    result = await db.execute(
        select(User).where(
            User.email_verify_token == _hash_token(token),
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


async def forgot_password(db: AsyncSession, email: str) -> str | None:
    """Returns raw reset token for Phase 5 email delivery, or None if email not found (silent)."""
    result = await db.execute(select(User).where(User.email == email, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if user is None:
        return None

    raw_token = secrets.token_urlsafe(32)
    user.password_reset_token = _hash_token(raw_token)
    user.password_reset_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await db.commit()
    return raw_token


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    result = await db.execute(
        select(User).where(User.password_reset_token == _hash_token(token))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("Invalid or expired reset token")
    if user.password_reset_token_expires_at and user.password_reset_token_expires_at < datetime.now(timezone.utc):
        raise ValueError("Reset token expired")

    user.hashed_password = hash_password(new_password)
    user.password_reset_token = None
    user.password_reset_token_expires_at = None

    await _revoke_all_refresh_tokens(db, user.id)
    await audit_service.log_event(db, action="auth.password_reset", actor_id=user.id)
    await db.commit()


async def change_password(db: AsyncSession, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.hashed_password):
        raise ValueError("Current password is incorrect")
    user.hashed_password = hash_password(new_password)
    await _revoke_all_refresh_tokens(db, user.id)
    await audit_service.log_event(db, action="auth.password_changed", actor_id=user.id)
    await db.commit()
