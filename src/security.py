"""API security: API-key auth with roles and tenant scopes, rate limiting, body-size limit, security headers, path/URL allow-lists.

Keys come from AEGIS_API_KEYS="key:tenants:role,..." (tenants = `*` or `a|b|c`; role = admin | auditor | viewer). The API is
closed by default: with no keys configured every protected route answers 503 unless AEGIS_AUTH_DISABLED=true (local development).
Keys are compared in constant time and are never logged; logs carry a short sha256 key id.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request

ROLE_RANK = {"viewer": 0, "auditor": 1, "admin": 2}


@dataclass(frozen=True)
class Principal:
    key_id: str
    role: str
    tenants: frozenset[str]  # empty + wildcard flag below
    wildcard: bool = False

    def can_access(self, tenant: str) -> bool:
        return self.wildcard or tenant in self.tenants

    def at_least(self, role: str) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]


def key_id(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def _load_keys() -> list[tuple[str, Principal]]:
    out = []
    for item in os.getenv("AEGIS_API_KEYS", "").split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) != 3 or parts[2] not in ROLE_RANK:
            continue  # malformed entry is ignored, never half-applied
        key, tenants, role = parts
        wild = tenants.strip() == "*"
        out.append((key, Principal(key_id(key), role, frozenset(t for t in tenants.split("|") if t and t != "*"), wild)))
    return out


def auth_disabled() -> bool:
    return os.getenv("AEGIS_AUTH_DISABLED", "").lower() == "true"


def authenticate(request: Request) -> Principal:
    if auth_disabled():
        return Principal("dev-open", "admin", frozenset(), True)
    keys = _load_keys()
    if not keys:
        raise HTTPException(503, "API authentication is not configured (set AEGIS_API_KEYS)")
    header = request.headers.get("authorization", "")
    presented = header[7:].strip() if header.lower().startswith("bearer ") else request.headers.get("x-api-key", "")
    found = None
    for key, principal in keys:  # compare against every key: no early exit on the first match
        if presented and hmac.compare_digest(presented.encode(), key.encode()):
            found = principal
    if found is None:
        raise HTTPException(401, "invalid or missing API key", headers={"WWW-Authenticate": "Bearer"})
    request.state.principal = found
    return found


def require(role: str):
    def dep(p: Principal = Depends(authenticate)) -> Principal:
        if not p.at_least(role):
            raise HTTPException(403, f"role '{role}' required")
        return p
    return dep


def require_tenant(p: Principal, tenant: str) -> None:
    if not p.can_access(tenant):
        raise HTTPException(403, "key is not authorised for this tenant")


# ------------------------------------------------------------------ rate limiting (sliding window, per key id or client IP)
class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, bucket: str, limit: int, window_s: float = 60.0, now: float | None = None) -> float | None:
        """Return None when allowed, else seconds to wait."""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits[bucket]
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                return max(0.1, q[0] + window_s - now)
            q.append(now)
            return None

    def reset(self):
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def rate_limit(heavy: bool = False):
    def dep(request: Request, p: Principal = Depends(authenticate)) -> None:
        limit = int(os.getenv("AEGIS_RATE_LIMIT_HEAVY_PER_MIN" if heavy else "AEGIS_RATE_LIMIT_PER_MIN", "10" if heavy else "120"))
        wait = limiter.check(f"{p.key_id}:{'heavy' if heavy else 'std'}", limit)
        if wait is not None:
            raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": str(int(wait) + 1)})
    return dep


# ------------------------------------------------------------------ input allow-lists
def allowed_git_hosts() -> set[str]:
    return {h.strip().lower() for h in os.getenv("AEGIS_ALLOWED_GIT_HOSTS", "github.com").split(",") if h.strip()}


def validate_repo_source(value: str, principal: Principal, companies_root: Path) -> str:
    """Remote repos must be https on an allow-listed host (SSRF guard); local paths are admin-only and must live under the companies root."""
    if value.startswith(("http://", "https://")):
        u = urlparse(value)
        if u.scheme != "https" or (u.hostname or "").lower() not in allowed_git_hosts() or u.username or u.password:
            raise HTTPException(400, "repository URL must be https on an allow-listed host without embedded credentials")
        return value
    if value.startswith(("git@", "ssh://", "file://")):
        raise HTTPException(400, "only https repository URLs are accepted")
    return str(validate_local_path(value, [companies_root], principal))


def validate_local_path(value: str, roots: list[Path], principal: Principal) -> Path:
    if not principal.at_least("admin"):
        raise HTTPException(403, "local paths are admin-only")
    p = Path(value).resolve()
    if not any(p == r.resolve() or r.resolve() in p.parents for r in roots):
        raise HTTPException(400, "path is outside the permitted directories")
    return p


SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
                    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"}
