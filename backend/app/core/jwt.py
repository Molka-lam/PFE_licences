from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from app.config import settings

ALGORITHM = "RS256"

from jose import JWTError as JWTError  # re-export


def create_access_token(subject: str, role: str) -> str:
    """Create a 15-minute RS256 access token. subject = user ID (str)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": subject,
        "role": role,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm=ALGORITHM)


def create_refresh_token(subject: str) -> str:
    """Create a 7-day RS256 refresh token."""
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": subject,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_PRIVATE_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and verify an RS256 token. Raises JWTError if invalid/expired."""
    return jwt.decode(token, settings.JWT_PUBLIC_KEY, algorithms=[ALGORITHM])
