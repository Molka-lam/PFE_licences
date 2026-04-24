import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.user import AdminUserUpdate, UserUpdate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    # AsyncMock auto-creates child attributes as AsyncMock; execute's return value
    # must be a plain MagicMock so .scalar_one_or_none() is called synchronously.
    db.execute.return_value = MagicMock()
    return db


def _make_user(**overrides) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "user@example.com"
    user.first_name = "Alice"
    user.last_name = "Smith"
    user.role = "client"
    user.is_active = True
    user.email_verified = True
    user.email_opt_in = True
    user.in_app_opt_in = True
    user.deleted_at = None
    for k, v in overrides.items():
        setattr(user, k, v)
    return user


# ---------------------------------------------------------------------------
# UserUpdate schema validation
# ---------------------------------------------------------------------------

class TestUserUpdateSchema:
    def test_all_fields_optional(self) -> None:
        body = UserUpdate()
        assert body.first_name is None
        assert body.email_opt_in is None

    def test_partial_update(self) -> None:
        body = UserUpdate(email_opt_in=False)
        assert body.email_opt_in is False
        assert body.first_name is None


# ---------------------------------------------------------------------------
# AdminUserUpdate schema validation
# ---------------------------------------------------------------------------

class TestAdminUserUpdateSchema:
    def test_invalid_role_rejected(self) -> None:
        with pytest.raises(Exception):
            AdminUserUpdate(role="superuser")  # not a valid Literal

    def test_valid_roles_accepted(self) -> None:
        for role in ("super_admin", "admin", "client"):
            body = AdminUserUpdate(role=role)
            assert body.role == role


# ---------------------------------------------------------------------------
# users.py route logic (isolated, no real DB)
# ---------------------------------------------------------------------------

class TestGetMe:
    async def test_returns_current_user(self) -> None:
        from app.api.v1.users import get_me
        user = _make_user()
        result = await get_me(current_user=user)
        assert result is user


class TestUpdateMe:
    async def test_applies_non_none_fields(self) -> None:
        from app.api.v1.users import update_me
        db = _make_db()
        user = _make_user(first_name="Alice", email_opt_in=True)
        body = UserUpdate(first_name="Bob", email_opt_in=False)
        db.refresh = AsyncMock(return_value=None)
        await update_me(body=body, current_user=user, db=db)
        assert user.first_name == "Bob"
        assert user.email_opt_in is False
        db.commit.assert_called_once()

    async def test_ignores_none_fields(self) -> None:
        from app.api.v1.users import update_me
        db = _make_db()
        user = _make_user(first_name="Alice")
        db.refresh = AsyncMock(return_value=None)
        await update_me(body=UserUpdate(), current_user=user, db=db)
        assert user.first_name == "Alice"  # unchanged


class TestChangeMyPassword:
    async def test_wrong_current_raises_400(self) -> None:
        from fastapi import HTTPException
        from app.api.v1.users import change_my_password
        db = _make_db()
        user = _make_user()
        body = MagicMock()
        body.current_password = "wrong"
        body.new_password = "newpass123"
        with patch("app.api.v1.users.auth_service.change_password", side_effect=ValueError("Current password is incorrect")):
            with pytest.raises(HTTPException) as exc_info:
                await change_my_password(body=body, current_user=user, db=db)
        assert exc_info.value.status_code == 400

    async def test_success_returns_message(self) -> None:
        from app.api.v1.users import change_my_password
        db = _make_db()
        user = _make_user()
        body = MagicMock()
        body.current_password = "correct"
        body.new_password = "newpass123"
        with patch("app.api.v1.users.auth_service.change_password", return_value=None):
            result = await change_my_password(body=body, current_user=user, db=db)
        assert "updated" in result.message.lower()


class TestGetUser:
    async def test_not_found_raises_404(self) -> None:
        from fastapi import HTTPException
        from app.api.v1.users import get_user
        db = _make_db()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await get_user(user_id=uuid.uuid4(), _admin=_make_user(role="admin"), db=db)
        assert exc_info.value.status_code == 404

    async def test_found_returns_user(self) -> None:
        from app.api.v1.users import get_user
        db = _make_db()
        target = _make_user()
        db.execute.return_value.scalar_one_or_none.return_value = target
        result = await get_user(user_id=target.id, _admin=_make_user(role="admin"), db=db)
        assert result is target


class TestUpdateUser:
    async def test_not_found_raises_404(self) -> None:
        from fastapi import HTTPException
        from app.api.v1.users import update_user
        db = _make_db()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await update_user(
                user_id=uuid.uuid4(),
                body=AdminUserUpdate(role="admin"),
                admin=_make_user(role="admin"),
                db=db,
            )
        assert exc_info.value.status_code == 404

    async def test_role_change_logged(self) -> None:
        from app.api.v1.users import update_user
        db = _make_db()
        target = _make_user(role="client")
        db.execute.return_value.scalar_one_or_none.return_value = target
        db.refresh = AsyncMock(return_value=None)
        with patch("app.api.v1.users.audit_service.log_event", new_callable=AsyncMock) as mock_log:
            await update_user(
                user_id=target.id,
                body=AdminUserUpdate(role="admin"),
                admin=_make_user(role="admin"),
                db=db,
            )
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs["action"] == "user.updated"
        assert call_kwargs["event_metadata"]["old_role"] == "client"

    async def test_is_active_change_logged(self) -> None:
        from app.api.v1.users import update_user
        db = _make_db()
        target = _make_user(role="client", is_active=True)
        db.execute.return_value.scalar_one_or_none.return_value = target
        db.refresh = AsyncMock(return_value=None)
        with patch("app.api.v1.users.audit_service.log_event", new_callable=AsyncMock) as mock_log:
            await update_user(
                user_id=target.id,
                body=AdminUserUpdate(is_active=False),
                admin=_make_user(role="admin"),
                db=db,
            )
        mock_log.assert_called_once()
        assert mock_log.call_args.kwargs["event_metadata"]["old_is_active"] is True

    async def test_self_modification_raises_400(self) -> None:
        from fastapi import HTTPException
        from app.api.v1.users import update_user
        db = _make_db()
        admin = _make_user(role="admin")
        with pytest.raises(HTTPException) as exc_info:
            await update_user(
                user_id=admin.id,  # same as admin's own id
                body=AdminUserUpdate(role="client"),
                admin=admin,
                db=db,
            )
        assert exc_info.value.status_code == 400

    async def test_no_change_no_audit_log(self) -> None:
        from app.api.v1.users import update_user
        db = _make_db()
        target = _make_user(role="client", is_active=True)
        db.execute.return_value.scalar_one_or_none.return_value = target
        db.refresh = AsyncMock(return_value=None)
        with patch("app.api.v1.users.audit_service.log_event", new_callable=AsyncMock) as mock_log:
            await update_user(
                user_id=target.id,
                body=AdminUserUpdate(role="client", is_active=True),  # same values
                admin=_make_user(role="admin"),
                db=db,
            )
        mock_log.assert_not_called()
