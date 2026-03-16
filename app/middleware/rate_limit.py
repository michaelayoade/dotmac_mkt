"""Redis-backed sliding window rate limiter for auth endpoints.

Protects login, password reset, and MFA verification from brute-force attacks.
"""

from __future__ import annotations

import logging
import os
import time
from ipaddress import (
    IPv4Address,
    IPv4Network,
    IPv6Address,
    IPv6Network,
    ip_address,
    ip_network,
)

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Paths and their rate limit configs: (max_requests, window_seconds)
_RATE_LIMIT_PATHS: dict[str, tuple[int, int]] = {
    "/auth/login": (10, 60),  # 10 attempts per minute
    "/auth/password-reset": (5, 300),  # 5 attempts per 5 minutes
    "/auth/mfa/verify": (10, 60),  # 10 attempts per minute
    "/auth/register": (5, 300),  # 5 registrations per 5 minutes
}
AUTH_PATHS: set[str] = {
    "/auth/login",
    "/auth/mfa",
    "/auth/register",
    "/auth/password-reset",
}

_TRUSTED_PROXY_CIDRS = os.getenv("TRUSTED_PROXY_CIDRS", "")


def _load_trusted_proxy_networks() -> list[IPv4Network | IPv6Network]:
    """Parse trusted proxy CIDRs from env, ignoring invalid entries."""
    networks: list[IPv4Network | IPv6Network] = []
    for raw_cidr in _TRUSTED_PROXY_CIDRS.split(","):
        cidr = raw_cidr.strip()
        if not cidr:
            continue
        try:
            networks.append(ip_network(cidr, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid TRUSTED_PROXY_CIDRS entry: %s", cidr)
    return networks


_TRUSTED_PROXY_NETWORKS = _load_trusted_proxy_networks()


def _parse_ip(value: str) -> IPv4Address | IPv6Address | None:
    """Best-effort parse of an IP address string."""
    try:
        return ip_address(value)
    except ValueError:
        return None


def _get_client_ip(request: Request) -> str:
    """Extract client IP, trusting proxy headers only from trusted proxies."""
    client = request.client
    if not client:
        return "unknown"

    direct_ip = client.host
    client_ip = _parse_ip(direct_ip)
    is_trusted_proxy = bool(
        client_ip and any(client_ip in network for network in _TRUSTED_PROXY_NETWORKS)
    )
    if not is_trusted_proxy:
        return direct_ip

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        forwarded_ip = forwarded.split(",", 1)[0].strip()
        if _parse_ip(forwarded_ip):
            return forwarded_ip

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        real_ip = real_ip.strip()
        if _parse_ip(real_ip):
            return real_ip

    return direct_ip


def _get_redis() -> object | None:
    """Lazy-connect to Redis. Returns None if unavailable."""
    try:
        import redis as redis_lib

        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        return redis_lib.Redis.from_url(url, decode_responses=True, socket_timeout=1)
    except Exception:
        logger.debug("Rate limiter: Redis unavailable, skipping")
        return None


def _is_auth_path(path: str) -> bool:
    return any(
        path.startswith(auth_path) or auth_path in path for auth_path in AUTH_PATHS
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiter for sensitive endpoints."""

    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._redis: object | None = None
        self._redis_checked = False

    def _ensure_redis(self) -> object | None:
        if not self._redis_checked:
            self._redis = _get_redis()
            self._redis_checked = True
        return self._redis

    async def dispatch(self, request: Request, call_next: object) -> Response:
        # Only rate-limit POST requests to auth paths
        if request.method != "POST":
            return await call_next(request)  # type: ignore[call-arg]

        path = request.url.path
        # Also check /api/v1 prefixed versions
        clean_path = (
            path.replace("/api/v1", "", 1) if path.startswith("/api/v1") else path
        )

        config = _RATE_LIMIT_PATHS.get(clean_path)
        if not config:
            return await call_next(request)  # type: ignore[call-arg]

        max_requests, window_seconds = config
        r = self._ensure_redis()
        if r is None:
            if _is_auth_path(clean_path):
                logger.warning(
                    "Rate limiter: Redis unavailable on auth path %s", clean_path
                )
            return await call_next(request)  # type: ignore[call-arg]

        client_ip = _get_client_ip(request)
        key = f"rate_limit:{clean_path}:{client_ip}"
        now = time.time()

        try:
            pipe = r.pipeline()  # type: ignore[union-attr]
            # Remove expired entries
            pipe.zremrangebyscore(key, 0, now - window_seconds)
            # Count remaining entries
            pipe.zcard(key)
            # Add current request
            pipe.zadd(key, {str(now): now})
            # Set expiry on the key
            pipe.expire(key, window_seconds)
            results = pipe.execute()
            current_count = results[1]
        except Exception:
            if _is_auth_path(clean_path):
                logger.warning("Rate limiter: Redis error on auth path %s", clean_path)
            else:
                logger.debug("Rate limiter: Redis error, allowing request")
            return await call_next(request)  # type: ignore[call-arg]

        if current_count >= max_requests:
            retry_after = str(window_seconds)
            logger.warning(
                "Rate limit exceeded: %s on %s (%d/%d)",
                client_ip,
                clean_path,
                current_count,
                max_requests,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "code": "rate_limit_exceeded",
                    "message": "Too many requests. Please try again later.",
                    "details": None,
                },
                headers={"Retry-After": retry_after},
            )

        response: Response = await call_next(request)  # type: ignore[call-arg]

        # Add rate limit headers for transparency
        remaining = max(0, max_requests - current_count - 1)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(now + window_seconds))

        return response
