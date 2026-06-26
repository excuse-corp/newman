from __future__ import annotations

import hmac
import logging
import os
import re
import secrets
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Request, Response

from backend.config.loader import get_project_dotenv_path, reload_settings, resolve_project_root
from backend.config.schema import AppConfig


LOGGER = logging.getLogger("newman.auth")
BOOTSTRAP_DIR_NAME = "bootstrap"
BOOTSTRAP_KEY_FILENAME = "setup-key.txt"
ADMIN_TOKEN_ENV_KEY = "NEWMAN_AUTH__ADMIN_TOKEN"
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{16,256}$")
STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class RequestAuthState:
    authenticated: bool
    method: str | None = None
    presented: bool = False
    invalid: bool = False


def is_auth_enabled(settings: AppConfig) -> bool:
    return bool(settings.auth.enabled)


def get_admin_token(settings: AppConfig) -> str | None:
    token = settings.auth.admin_token
    if not isinstance(token, str):
        return None
    normalized = token.strip()
    return normalized or None


def needs_bootstrap(settings: AppConfig) -> bool:
    return is_auth_enabled(settings) and not get_admin_token(settings)


def validate_admin_token(raw_token: str) -> str:
    token = raw_token.strip()
    if not TOKEN_PATTERN.fullmatch(token):
        raise ValueError("实例访问密钥只允许字母、数字、点、下划线、短横线和波浪号，长度需在 16 到 256 之间。")
    return token


def generate_admin_token() -> str:
    return secrets.token_urlsafe(32).replace("-", "_")[:43]


def ensure_bootstrap_key(settings: AppConfig) -> Path:
    bootstrap_dir = settings.paths.data_dir / BOOTSTRAP_DIR_NAME
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    key_path = bootstrap_dir / BOOTSTRAP_KEY_FILENAME
    if key_path.exists():
        return key_path
    setup_key = secrets.token_urlsafe(24)
    key_path.write_text(setup_key, encoding="utf-8")
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    LOGGER.warning("Admin auth is not configured. Setup key written to %s", key_path)
    return key_path


def read_bootstrap_key(settings: AppConfig) -> str | None:
    if not needs_bootstrap(settings) or not settings.auth.bootstrap_key_required:
        return None
    key_path = ensure_bootstrap_key(settings)
    value = key_path.read_text(encoding="utf-8").strip()
    return value or None


def delete_bootstrap_key(settings: AppConfig) -> None:
    key_path = settings.paths.data_dir / BOOTSTRAP_DIR_NAME / BOOTSTRAP_KEY_FILENAME
    if key_path.exists():
        key_path.unlink()


def verify_bootstrap_key(settings: AppConfig, candidate: str) -> bool:
    expected = read_bootstrap_key(settings)
    if not expected:
        return False
    return hmac.compare_digest(expected, candidate.strip())


def verify_admin_token(settings: AppConfig, candidate: str) -> bool:
    expected = get_admin_token(settings)
    if not expected:
        return False
    return hmac.compare_digest(expected, candidate.strip())


def resolve_request_auth(request: Request, settings: AppConfig) -> RequestAuthState:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        return RequestAuthState(
            authenticated=verify_admin_token(settings, token),
            method="bearer",
            presented=True,
            invalid=not verify_admin_token(settings, token),
        )

    cookie_value = request.cookies.get(settings.auth.cookie_name)
    if cookie_value:
        return RequestAuthState(
            authenticated=verify_admin_token(settings, cookie_value),
            method="cookie",
            presented=True,
            invalid=not verify_admin_token(settings, cookie_value),
        )

    return RequestAuthState(authenticated=False)


def set_auth_cookie(response: Response, request: Request, settings: AppConfig, token: str) -> None:
    secure = settings.auth.cookie_secure or _is_https_request(request)
    response.set_cookie(
        key=settings.auth.cookie_name,
        value=token,
        httponly=True,
        secure=secure,
        samesite=settings.auth.cookie_samesite,
        max_age=settings.auth.session_ttl_hours * 3600,
        path="/",
    )


def clear_auth_cookie(response: Response, settings: AppConfig) -> None:
    response.delete_cookie(key=settings.auth.cookie_name, path="/")


def ensure_state_changing_origin_allowed(request: Request, settings: AppConfig, *, auth_method: str | None) -> bool:
    if request.method.upper() not in STATE_CHANGING_METHODS:
        return True
    if auth_method != "cookie":
        return True
    origin = _extract_request_origin(request)
    if origin is None:
        return False
    return origin in _allowed_origins(request, settings)


def bootstrap_key_location_hint(settings: AppConfig) -> str:
    key_path = settings.paths.data_dir / BOOTSTRAP_DIR_NAME / BOOTSTRAP_KEY_FILENAME
    return str(key_path)


def persist_admin_token(request: Request, token: str) -> AppConfig:
    return persist_project_env_updates(request, {ADMIN_TOKEN_ENV_KEY: token})


def persist_project_env_updates(
    request: Request,
    updates: Mapping[str, str],
    *,
    reload_settings_after_write: bool = True,
) -> AppConfig | None:
    project_root = resolve_project_root(_project_root_value(request))
    dotenv_path = get_project_dotenv_path(str(project_root))
    _upsert_dotenv_keys(dotenv_path, updates)
    os.environ.update({key: value for key, value in updates.items()})
    if not reload_settings_after_write:
        return None
    next_settings = reload_settings(str(project_root))
    request.app.state.settings = next_settings
    return next_settings


def announce_bootstrap_state(settings: AppConfig) -> None:
    if needs_bootstrap(settings) and settings.auth.bootstrap_key_required:
        ensure_bootstrap_key(settings)


def _project_root_value(request: Request) -> str | None:
    project_root = getattr(request.app.state, "project_root", None)
    if project_root is None:
        return None
    return str(project_root)


def _upsert_dotenv_key(path: Path, key: str, value: str) -> None:
    _upsert_dotenv_keys(path, {key: value})


def _upsert_dotenv_keys(path: Path, updates: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated_lines: list[str] = []
    pending = {key: value for key, value in updates.items()}
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            updated_lines.append(raw_line)
            continue
        current_key, _current_value = raw_line.split("=", 1)
        normalized_key = current_key.strip()
        if normalized_key in pending:
            updated_lines.append(f"{normalized_key}={pending.pop(normalized_key)}")
        else:
            updated_lines.append(raw_line)
    for key, value in pending.items():
        updated_lines.append(f"{key}={value}")
    rendered = "\n".join(updated_lines).rstrip()
    path.write_text(f"{rendered}\n" if rendered else "", encoding="utf-8")


def _allowed_origins(request: Request, settings: AppConfig) -> set[str]:
    allowed = {value for value in (_normalize_origin(item) for item in settings.server.cors_origins) if value}
    current_origin = _current_request_origin(request)
    if current_origin:
        allowed.add(current_origin)
    return allowed


def _extract_request_origin(request: Request) -> str | None:
    for header_name in ("origin", "referer"):
        value = request.headers.get(header_name)
        normalized = _normalize_origin(value)
        if normalized:
            return normalized
    return None


def _current_request_origin(request: Request) -> str | None:
    host = _forwarded_host(request) or request.headers.get("host")
    if not host:
        return None
    scheme = _forwarded_proto(request) or request.url.scheme
    return _normalize_origin(f"{scheme}://{host}")


def _normalize_origin(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _forwarded_proto(request: Request) -> str | None:
    raw_value = request.headers.get("x-forwarded-proto")
    if not raw_value:
        return None
    first = raw_value.split(",", 1)[0].strip().lower()
    return first or None


def _forwarded_host(request: Request) -> str | None:
    raw_value = request.headers.get("x-forwarded-host")
    if not raw_value:
        return None
    first = raw_value.split(",", 1)[0].strip()
    return first or None


def _is_https_request(request: Request) -> bool:
    forwarded = _forwarded_proto(request)
    return forwarded == "https" or request.url.scheme == "https"
