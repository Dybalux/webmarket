"""Idempotency helpers for POST endpoints.

Provides Redis-backed idempotency via SET NX with a two-phase pattern:
  1. SET key IN_FLIGHT NX EX ttl  →  run handler
  2. SET key <cached_json> KEEPTTL  →  return response

Design decisions (see design.md):
  ADR-4: two-phase Redis (SET NX + KEEPTTL)
  ADR-5: fail-open when Redis is down
  ADR-6: fallback key = sha256(user_id | endpoint | canonical_json(payload))

Key namespace: idem:{user_id}:{endpoint}:{uuid | fb:hash}
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from typing import Any, Awaitable, Callable, TypeVar

from fastapi import HTTPException, status
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Sentinel stored while handler is still running.
_IN_FLIGHT = "__IN_FLIGHT__"

# UUID-4 pattern: 8-4-4-4-12 hex with version nibble = 4.
_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

T = TypeVar("T")


def _to_jsonable(obj: Any) -> Any:
    """Convert an object to a JSON-serializable form.

    Handles Pydantic models (via model_dump), datetimes, Decimals, etc.
    Used as the ``default`` hook for json.dumps.
    """
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_key(header: str | None) -> str | None:
    """Validate an Idempotency-Key header as UUID-4.

    Returns the normalised (lowercase) key string, or None when the
    header is absent.  Raises HTTPException 400 when present but invalid.
    """
    if header is None:
        return None
    cleaned = header.strip()
    if not cleaned:
        return None
    if not _UUID4_RE.match(cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key inválido: debe ser un UUID v4.",
        )
    return cleaned.lower()


def fallback_key(user_id: str, endpoint: str, payload: BaseModel | str) -> str:
    """Derive a deterministic key when the client omits the header.

    Key = sha256(user_id | endpoint | canonical_json(payload)) truncated to 32 hex.
    Accepts either a Pydantic model (serialized via model_dump_json) or a plain
    string (used for endpoints with no request body, e.g. path-param-only).
    """
    if isinstance(payload, BaseModel):
        canonical = payload.model_dump_json()
    else:
        canonical = str(payload)
    raw = f"{user_id}|{endpoint}|{canonical}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"fb:{digest}"


async def get_or_set(
    redis: Redis,
    key: str,
    producer: Callable[[], Awaitable[T]],
    *,
    ttl: int = 86_400,
) -> tuple[T, bool]:
    """Two-phase idempotent execution.

    Returns (result, was_cached).
      - First call: runs producer(), caches JSON, returns (result, False).
      - Replay within TTL: returns cached JSON, (result, True).
      - Duplicate while IN_FLIGHT: raises 409.
      - Redis down: runs producer() without caching (fail-open).

    Raises:
        HTTPException 409 — duplicate request still being processed.
    """
    try:
        # Phase 1: attempt to claim the key.
        claimed = await redis.set(key, _IN_FLIGHT, nx=True, ex=ttl)
        if not claimed:
            # Key already exists — check if it's still IN_FLIGHT or cached.
            cached = await redis.get(key)
            if cached == _IN_FLIGHT:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "idempotency_in_progress",
                        "message": "Solicitud duplicada en procesamiento.",
                    },
                )
            # Cached response — replay.
            return json.loads(cached), True

        # Phase 2: execute the handler.
        result = await producer()

        # Phase 3: persist cached response (keep the remaining TTL).
        try:
            await redis.set(key, json.dumps(result, default=_to_jsonable), keepttl=True)
        except RedisError:
            # Non-fatal: key will expire; next request re-executes.
            logger.warning("Failed to cache idempotency result for %s", key)

        return result, False

    except HTTPException:
        raise
    except RedisError as exc:
        # ADR-5: fail-open — log and proceed without idempotency.
        logger.warning(
            "Redis error on idempotency key %s — proceeding without idempotency: %s",
            key, exc,
        )
        result = await producer()
        return result, False


def build_key(user_id: str, endpoint: str, idempotency_key: str | None) -> str:
    """Build the full Redis key with namespace.

    Format: idem:{user_id}:{endpoint}:{uuid | fb:hash}
    """
    suffix = idempotency_key if idempotency_key else "fb:missing"
    return f"idem:{user_id}:{endpoint}:{suffix}"
