import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from unittest.mock import patch


def make_rsa_key_pair() -> tuple[str, str]:
    """Generate a fresh RSA-2048 key pair, return (private_pem, public_pem)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


@pytest.fixture
def rsa_keys():
    return make_rsa_key_pair()


def test_create_and_decode_access_token(rsa_keys):
    private_pem, public_pem = rsa_keys
    with patch("app.core.jwt.settings") as mock_settings:
        mock_settings.JWT_PRIVATE_KEY = private_pem
        mock_settings.JWT_PUBLIC_KEY = public_pem
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 15
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        from app.core.jwt import create_access_token, decode_token
        token = create_access_token("user-123", "client")
        payload = decode_token(token)
        assert payload["sub"] == "user-123"
        assert payload["role"] == "client"
        assert payload["type"] == "access"


def test_refresh_token_type(rsa_keys):
    private_pem, public_pem = rsa_keys
    with patch("app.core.jwt.settings") as mock_settings:
        mock_settings.JWT_PRIVATE_KEY = private_pem
        mock_settings.JWT_PUBLIC_KEY = public_pem
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 15
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        from app.core.jwt import create_refresh_token, decode_token
        token = create_refresh_token("user-456")
        payload = decode_token(token)
        assert payload["sub"] == "user-456"
        assert payload["type"] == "refresh"


def test_invalid_token_raises(rsa_keys):
    _, public_pem = rsa_keys
    with patch("app.core.jwt.settings") as mock_settings:
        mock_settings.JWT_PUBLIC_KEY = public_pem
        from app.core.jwt import decode_token, JWTError
        with pytest.raises(JWTError):
            decode_token("not.a.valid.token")
