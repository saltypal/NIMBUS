"""Small shared helpers; no hidden state or initialization."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(UTC)


def identifier(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def json_default(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def fingerprint(value) -> str:
    canonical = json.dumps(
        value, default=json_default, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_time(value) -> datetime:
    moment = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if moment.tzinfo is None:
        raise ValueError("Time must include its timezone")
    return moment.astimezone(UTC)
