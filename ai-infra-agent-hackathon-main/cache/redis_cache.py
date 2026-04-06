"""
cache/redis_cache.py — Redis-backed scan result cache.
Status: IMPLEMENTED

Replaces the PostgreSQL scan_cache column approach with Redis.
Key format: scan:{region}  (shared across sessions — same region = same data)
TTL is enforced natively by Redis SETEX.

Falls back gracefully to None on any Redis error — callers treat None as a
cache miss and fetch fresh from AWS.

Requires: redis>=5.0.0
Env var:  REDIS_URL (default: redis://localhost:6379)
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
def _get_client():
    """
    Return a Redis client. Creates a new connection each call — avoids
    stale singleton issues when the module is reloaded by Streamlit reruns.
    Returns None if redis is not installed or connection fails.
    """
    try:
        import redis
        client = redis.from_url(_REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception as exc:
        logger.warning("Redis unavailable: %s — cache disabled", exc)
        return None


def _cache_key(region: str) -> str:
    """
    Cache key is region-scoped — shared across all sessions for the same region.
    This means if two users scan us-east-1, the second gets instant results.
    """
    return f"scan:{region}"


def get_scan_cache(session_id: str, region: str, ttl_minutes: int = 10) -> Optional[dict]:
    """
    Return cached scan data for the region if it exists and is within TTL.
    session_id is accepted for API compatibility but not used as part of the key —
    Redis TTL handles expiry natively so we don't need per-session cache entries.

    Returns None on cache miss, TTL expiry, or any Redis error.
    """
    client = _get_client()
    if client is None:
        return None
    try:
        data = client.get(_cache_key(region))
        if data is None:
            return None
        result = json.loads(data)
        logger.debug("Redis cache hit for region=%s", region)
        return result
    except Exception as exc:
        logger.warning("Redis get_scan_cache failed for region=%s: %s", region, exc)
        return None


def write_scan_cache(session_id: str, region: str, scan_data, ttl_minutes: int = 10) -> None:
    """
    Write scan results to Redis with a TTL.
    Pass scan_data=None to delete the cache key (forces re-fetch on next call).
    No-op on any Redis error — never raises.
    """
    client = _get_client()
    if client is None:
        return
    key = _cache_key(region)
    try:
        if scan_data is None:
            client.delete(key)
            logger.debug("Redis cache cleared for region=%s", region)
        else:
            client.setex(key, ttl_minutes * 60, json.dumps(scan_data))
            logger.debug("Redis cache written for region=%s (TTL=%dm)", region, ttl_minutes)
    except Exception as exc:
        logger.warning("Redis write_scan_cache failed for region=%s: %s", region, exc)
