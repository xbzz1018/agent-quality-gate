import json
import os
from dataclasses import dataclass, field
from typing import Literal

AuthKind = Literal["headers", "bearer_login", "cookie_login"]


@dataclass(frozen=True, slots=True)
class ResolvedAuth:
    kind: AuthKind = "headers"
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)


def resolve_auth(auth_ref: str | None) -> ResolvedAuth:
    if auth_ref is None:
        return ResolvedAuth()
    raw = os.getenv(auth_ref)
    if raw is None:
        raise RuntimeError(f"auth reference environment variable is not set: {auth_ref}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("auth reference must contain valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("auth reference must contain a JSON object")
    if "type" not in value and all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        return ResolvedAuth(headers=dict(value))
    kind = value.get("type", "headers")
    if kind not in {"headers", "bearer_login", "cookie_login"}:
        raise ValueError("auth reference type must be headers, bearer_login, or cookie_login")
    headers = value.get("headers", {})
    if not isinstance(headers, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in headers.items()
    ):
        raise ValueError("auth headers must be a JSON object of strings")
    username = value.get("username")
    password = value.get("password")
    if kind != "headers" and (
        not isinstance(username, str)
        or not username
        or not isinstance(password, str)
        or not password
    ):
        raise ValueError("login auth requires non-empty username and password")
    return ResolvedAuth(
        kind=kind,
        headers=dict(headers),
        username=username,
        password=password,
    )
