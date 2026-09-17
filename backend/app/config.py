"""Environment-backed configuration.

Production requires explicit secrets.  Development may generate process-local
secrets so a fresh checkout can be exercised without accidentally checking a
credential into source control.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


class ConfigurationError(RuntimeError):
    """Raised when an unsafe production configuration is requested."""


DEFAULT_SESSION_TTL_SECONDS = 180 * 24 * 60 * 60
DEFAULT_SESSION_REFRESH_INTERVAL_SECONDS = 15 * 60


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


def _parse_origins(value: str | None, public_base_url: str | None) -> tuple[str, ...]:
    raw = [part.strip().rstrip("/") for part in (value or "").split(",") if part.strip()]
    if not raw and public_base_url:
        parsed = urlparse(public_base_url)
        if parsed.scheme and parsed.netloc:
            raw = [f"{parsed.scheme}://{parsed.netloc}"]
    origins: list[str] = []
    for origin in raw:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
            raise ConfigurationError("BOT_ALLOWED_ORIGINS must contain HTTP(S) origins")
        origins.append(origin)
    return tuple(dict.fromkeys(origins))


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the standalone bot-mode service."""

    environment: str = "development"
    database_path: Path = Path("data/bot-mode.sqlite3")
    workspace_root: Path = Path("data/workspaces")
    internal_secret: str = ""
    session_secret: str = ""
    public_base_url: str | None = None
    allowed_origins: tuple[str, ...] = field(default_factory=tuple)
    cookie_name: str = "dad_bot_session"
    cookie_secure: bool = False
    cookie_path: str = "/bot"
    # The session expiry is a rolling inactivity deadline.  Active devices
    # remain signed in while an idle device expires after six months.
    session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS
    session_refresh_interval_seconds: int = DEFAULT_SESSION_REFRESH_INTERVAL_SECONDS
    nonce_ttl_seconds: int = 5 * 60
    max_file_bytes: int = 10 * 1024 * 1024
    max_memory_chars: int = 50_000
    max_message_chars: int = 100_000
    bind_host: str = "127.0.0.1"
    bind_port: int = 9120
    default_model: str = "gpt-5.6-luna"

    def __post_init__(self) -> None:
        if self.production:
            missing: list[str] = []
            if len(self.internal_secret) < 32:
                missing.append("BOT_INTERNAL_SECRET")
            if len(self.session_secret) < 32:
                missing.append("BOT_SESSION_SECRET")
            if not self.public_base_url:
                missing.append("BOT_PUBLIC_BASE_URL")
            if not self.allowed_origins:
                missing.append("BOT_ALLOWED_ORIGINS")
            if not self.cookie_secure:
                missing.append("BOT_COOKIE_SECURE=true")
            if missing:
                raise ConfigurationError("Production requires: " + ", ".join(missing))
        if self.cookie_path != "/bot":
            raise ConfigurationError("Bot-mode session cookies must be scoped to /bot")
        if (
            self.session_ttl_seconds <= 0
            or self.session_refresh_interval_seconds <= 0
            or self.nonce_ttl_seconds <= 0
        ):
            raise ConfigurationError("Session, session refresh, and nonce TTLs must be positive")

    @property
    def production(self) -> bool:
        return self.environment.lower() in {"prod", "production"}

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.getenv("BOT_ENV", "development").strip().lower()
        production = environment in {"prod", "production"}
        internal_secret = os.getenv("BOT_INTERNAL_SECRET", "")
        session_secret = os.getenv("BOT_SESSION_SECRET", "")
        public_base_url = os.getenv("BOT_PUBLIC_BASE_URL")
        if not production:
            # These are generated per process and are never persisted in source.
            # Operators should still set stable values when running multiple
            # workers or restarting the service.
            internal_secret = internal_secret or secrets.token_urlsafe(32)
            session_secret = session_secret or secrets.token_urlsafe(32)
        if production:
            missing = []
            if len(internal_secret) < 32:
                missing.append("BOT_INTERNAL_SECRET")
            if len(session_secret) < 32:
                missing.append("BOT_SESSION_SECRET")
            if not public_base_url:
                missing.append("BOT_PUBLIC_BASE_URL")
            if missing:
                raise ConfigurationError(
                    "Production requires configured secrets/base URL: " + ", ".join(missing)
                )
        cookie_secure = _env_bool("BOT_COOKIE_SECURE", production)
        cookie_name = os.getenv(
            "BOT_COOKIE_NAME",
            "__Secure-dad_bot_session" if cookie_secure else "dad_bot_session",
        )
        if cookie_secure and not cookie_name.startswith("__Secure-"):
            # A Secure cookie may use a normal name, but the prefix makes the
            # security invariant visible and avoids accidental broadening.
            cookie_name = "__Secure-" + cookie_name
        origins = _parse_origins(os.getenv("BOT_ALLOWED_ORIGINS"), public_base_url)
        if production and not origins:
            raise ConfigurationError("Production requires BOT_ALLOWED_ORIGINS or BOT_PUBLIC_BASE_URL")
        max_file_bytes = _env_int("BOT_MAX_FILE_BYTES", 10 * 1024 * 1024)
        if max_file_bytes <= 0:
            raise ConfigurationError("BOT_MAX_FILE_BYTES must be positive")
        return cls(
            environment=environment,
            database_path=Path(os.getenv("BOT_DATABASE_PATH", "data/bot-mode.sqlite3")),
            workspace_root=Path(os.getenv("BOT_WORKSPACE_ROOT", "data/workspaces")),
            internal_secret=internal_secret,
            session_secret=session_secret,
            public_base_url=public_base_url.rstrip("/") if public_base_url else None,
            allowed_origins=origins,
            cookie_name=cookie_name,
            cookie_secure=cookie_secure,
            session_ttl_seconds=_env_int("BOT_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS),
            session_refresh_interval_seconds=_env_int(
                "BOT_SESSION_REFRESH_INTERVAL_SECONDS", DEFAULT_SESSION_REFRESH_INTERVAL_SECONDS
            ),
            nonce_ttl_seconds=_env_int("BOT_NONCE_TTL_SECONDS", 5 * 60),
            max_file_bytes=max_file_bytes,
            max_memory_chars=_env_int("BOT_MAX_MEMORY_CHARS", 50_000),
            max_message_chars=_env_int("BOT_MAX_MESSAGE_CHARS", 100_000),
            bind_host=os.getenv("BOT_BIND_HOST", "127.0.0.1"),
            bind_port=_env_int("BOT_BIND_PORT", 9120),
            default_model=os.getenv("BOT_DEFAULT_MODEL", "gpt-5.6-luna"),
        )

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)

