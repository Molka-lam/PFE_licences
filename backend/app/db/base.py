from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import all models so Alembic can detect them
from app.models import (  # noqa: F401, E402
    user,
    refresh_token,
    plan,
    application,
    license,
    license_transition,
    license_key,
    notification,
    usage_record,
    audit_log,
    webhook,
)
