from unittest.mock import Mock

import jwt
import pytest

from agent_quality_harness.core.config import Settings
from agent_quality_harness.security import (
    audit,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_argon2id_password_hash_round_trip() -> None:
    password_hash = hash_password("A-strong-password-123")

    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, "A-strong-password-123") is True
    assert verify_password(password_hash, "wrong-password") is False


def test_audit_redacts_password_tokens_keys_and_auth_references() -> None:
    session = Mock()

    row = audit(
        session,
        action="member.update",
        outcome="success",
        details={
            "new_password": "plain text",
            "refresh_token": "token",
            "nested": {"api_key": "key", "auth_ref": "vault://secret"},
            "safe": "visible",
        },
    )

    assert row.details == {
        "new_password": "[REDACTED]",
        "refresh_token": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]", "auth_ref": "[REDACTED]"},
        "safe": "visible",
    }


def test_expired_access_token_is_rejected() -> None:
    settings = Settings(jwt_secret="test-secret-that-is-longer-than-thirty-two-bytes")
    token = jwt.encode(
        {"sub": "1", "typ": "access", "exp": 1},
        settings.jwt_secret,
        algorithm="HS256",
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token, settings)
