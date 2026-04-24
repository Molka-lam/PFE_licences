import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import JWTError

from app.services.auth_service import (
    _hash_token,
    change_password,
    forgot_password,
    login_user,
    logout_user,
    register_user,
    reset_password,
    verify_email,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    return db


def _make_user(**overrides) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "user@example.com"
    user.hashed_password = "hashed"
    user.role = "client"
    user.is_active = True
    user.email_verified = False
    user.email_verify_token = None
    user.email_verify_token_expires_at = None
    user.password_reset_token = None
    user.password_reset_token_expires_at = None
    user.deleted_at = None
    for key, val in overrides.items():
        setattr(user, key, val)
    return user


# ---------------------------------------------------------------------------
# _hash_token
# ---------------------------------------------------------------------------

class TestHashToken:
    def test_deterministic(self) -> None:
        t = "some-token"
        assert _hash_token(t) == _hash_token(t)

    def test_matches_sha256(self) -> None:
        t = "abc123"
        assert _hash_token(t) == hashlib.sha256(t.encode()).hexdigest()

    def test_length_64(self) -> None:
        assert len(_hash_token("anything")) == 64


# ---------------------------------------------------------------------------
# register_user
# ---------------------------------------------------------------------------

class TestRegisterUser:
    async def test_email_taken_raises(self) -> None:
        db = _make_db()
        db.execute.return_value.scalar_one_or_none.return_value = _make_user()
        with pytest.raises(ValueError, match="already registered"):
            await register_user(db, "taken@example.com", "password123", None, None)

    async def test_success_commits_and_refreshes(self) -> None:
        db = _make_db()
        db.execute.return_value.scalar_one_or_none.return_value = None
        await register_user(db, "new@example.com", "password123", "Alice", None)
        db.add.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()


# ---------------------------------------------------------------------------
# login_user
# ---------------------------------------------------------------------------

class TestLoginUser:
    async def test_user_not_found_raises(self) -> None:
        db = _make_db()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(ValueError, match="Invalid credentials"):
            await login_user(db, "nobody@example.com", "pass")

    async def test_wrong_password_raises(self) -> None:
        db = _make_db()
        db.execute.return_value.scalar_one_or_none.return_value = _make_user()
        with patch("app.services.auth_service.verify_password", return_value=False):
            with pytest.raises(ValueError, match="Invalid credentials"):
                await login_user(db, "user@example.com", "wrong")

    async def test_inactive_user_raises(self) -> None:
        db = _make_db()
        db.execute.return_value.scalar_one_or_none.return_value = _make_user(is_active=False)
        with patch("app.services.auth_service.verify_password", return_value=True):
            with pytest.raises(ValueError, match="disabled"):
                await login_user(db, "user@example.com", "pass")

    async def test_success_returns_token_pair(self) -> None:
        db = _make_db()
        db.execute.return_value.scalar_one_or_none.return_value = _make_user()
        with (
            patch("app.services.auth_service.verify_password", return_value=True),
            patch("app.services.auth_service.create_access_token", return_value="acc"),
            patch("app.services.auth_service.create_refresh_token", return_value="ref"),
        ):
            access, refresh = await login_user(db, "user@example.com", "pass")
        assert access == "acc"
        assert refresh == "ref"
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# verify_email
# ---------------------------------------------------------------------------

class TestVerifyEmail:
    async def test_unknown_token_raises(self) -> None:
        db = _make_db()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(ValueError, match="Invalid or expired"):
            await verify_email(db, "bad-token")

    async def test_expired_token_raises(self) -> None:
        db = _make_db()
        user = _make_user(
            email_verify_token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1)
        )
        db.execute.return_value.scalar_one_or_none.return_value = user
        with pytest.raises(ValueError, match="expired"):
            await verify_email(db, "stale-token")

    async def test_success_marks_verified(self) -> None:
        db = _make_db()
        user = _make_user(
            email_verify_token="tok",
            email_verify_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.execute.return_value.scalar_one_or_none.return_value = user
        await verify_email(db, "tok")
        assert user.email_verified is True
        assert user.email_verify_token is None
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# forgot_password
# ---------------------------------------------------------------------------

class TestForgotPassword:
    async def test_unknown_email_is_silent(self) -> None:
        db = _make_db()
        db.execute.return_value.scalar_one_or_none.return_value = None
        await forgot_password(db, "ghost@example.com")
        db.commit.assert_not_called()

    async def test_known_email_sets_reset_token(self) -> None:
        db = _make_db()
        user = _make_user()
        db.execute.return_value.scalar_one_or_none.return_value = user
        await forgot_password(db, "user@example.com")
        assert user.password_reset_token is not None
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# reset_password
# ---------------------------------------------------------------------------

class TestResetPassword:
    async def test_invalid_token_raises(self) -> None:
        db = _make_db()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(ValueError, match="Invalid or expired"):
            await reset_password(db, "bad", "newpass123")

    async def test_expired_token_raises(self) -> None:
        db = _make_db()
        user = _make_user(
            password_reset_token="tok",
            password_reset_token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db.execute.return_value.scalar_one_or_none.return_value = user
        with pytest.raises(ValueError, match="expired"):
            await reset_password(db, "tok", "newpass123")

    async def test_success_updates_hash_and_clears_token(self) -> None:
        db = _make_db()
        user = _make_user(
            password_reset_token="valid",
            password_reset_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.execute.return_value.scalar_one_or_none.return_value = user
        with patch("app.services.auth_service.hash_password", return_value="new-hash"):
            await reset_password(db, "valid", "newpass123")
        assert user.hashed_password == "new-hash"
        assert user.password_reset_token is None
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# change_password
# ---------------------------------------------------------------------------

class TestChangePassword:
    async def test_wrong_current_password_raises(self) -> None:
        db = _make_db()
        user = _make_user()
        with patch("app.services.auth_service.verify_password", return_value=False):
            with pytest.raises(ValueError, match="Current password is incorrect"):
                await change_password(db, user, "wrong", "newpass123")

    async def test_success_updates_hash(self) -> None:
        db = _make_db()
        user = _make_user()
        with (
            patch("app.services.auth_service.verify_password", return_value=True),
            patch("app.services.auth_service.hash_password", return_value="updated-hash"),
        ):
            await change_password(db, user, "correct", "newpass123")
        assert user.hashed_password == "updated-hash"
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# logout_user
# ---------------------------------------------------------------------------

class TestLogoutUser:
    async def test_revokes_refresh_token_and_logs(self) -> None:
        db = _make_db()
        rt = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = rt
        user_id = uuid.uuid4()
        await logout_user(db, "some-raw-token", user_id)
        assert rt.revoked is True
        db.add.assert_called_once()
        db.commit.assert_called_once()

    async def test_no_matching_token_still_logs(self) -> None:
        db = _make_db()
        db.execute.return_value.scalar_one_or_none.return_value = None
        user_id = uuid.uuid4()
        await logout_user(db, "unknown-token", user_id)
        db.add.assert_called_once()  # AuditLog still added
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# refresh_tokens
# ---------------------------------------------------------------------------

class TestRefreshTokens:
    async def test_invalid_jwt_raises(self) -> None:
        db = _make_db()
        # decode_refresh_token is imported locally inside refresh_tokens(), so patch at source
        with patch("app.core.jwt.decode_refresh_token", side_effect=JWTError("bad")):
            from app.services.auth_service import refresh_tokens
            with pytest.raises(ValueError, match="Invalid or expired"):
                await refresh_tokens(db, "garbage")
