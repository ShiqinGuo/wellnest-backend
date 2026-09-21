import os
from dataclasses import dataclass


def runtime_value(env, key: str, default: str | None = None) -> str | None:
    return getattr(env, key, default) if env is not None else os.getenv(key, default)


@dataclass(frozen=True)
class RuntimeSettings:
    database_timeout_seconds: float = 10
    session_lifetime_days: int = 30
    seconds_per_day: int = 86400
    token_entropy_bytes: int = 32
    max_token_length: int = 200
    idempotency_key_min_length: int = 8
    idempotency_key_max_length: int = 128
    session_cookie: str = "wellnest_session"


RUNTIME = RuntimeSettings()
