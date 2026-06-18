"""
Authentication layer.

Uses Supabase Auth (JWT) as the identity provider.
The FastAPI middleware validates JWTs on every protected request.

Two modes:
  1. Supabase-issued JWTs (production) — verified against Supabase JWKS
  2. Local JWTs (development) — signed with SECRET_KEY, issued by /auth/token

Protected routes use the `require_user` dependency.
Optional auth uses `optional_user` (returns None if no token).

User tiers:
  free        — 10K paper graph, 50 copilot queries/month
  researcher  — full graph, unlimited queries, API key
  admin       — full access + model training triggers
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from loguru import logger

from core.config import get_settings

settings = get_settings()

# ── CRYPTO ────────────────────────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7   # 7 days


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(
    user_id: str,
    email: str,
    tier: str = "free",
    expires_delta: timedelta | None = None,
) -> str:
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub":   user_id,
        "email": email,
        "tier":  tier,
        "exp":   expire,
        "iat":   datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


# ── USER MODEL ────────────────────────────────────────────────────────────────

class User(BaseModel):
    id: str
    email: str
    tier: str = "free"           # free | researcher | admin
    is_active: bool = True

    @property
    def is_admin(self) -> bool:
        return self.tier == "admin"

    @property
    def is_researcher(self) -> bool:
        return self.tier in ("researcher", "admin")

    @property
    def monthly_query_limit(self) -> int | None:
        limits = {"free": 50, "researcher": None, "admin": None}
        return limits.get(self.tier, 50)


# ── JWT VALIDATION ────────────────────────────────────────────────────────────

def _decode_local_jwt(token: str) -> dict:
    """Decode a locally-issued JWT (development mode)."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


def _decode_supabase_jwt(token: str) -> dict:
    """
    Decode a Supabase-issued JWT.
    In production, Supabase JWTs use a project-specific JWT secret.
    We verify using the same secret stored in SUPABASE_JWT_SECRET env var.
    """
    supabase_secret = getattr(settings, "SUPABASE_JWT_SECRET", None)
    if not supabase_secret:
        raise JWTError("SUPABASE_JWT_SECRET not configured")
    return jwt.decode(token, supabase_secret, algorithms=[ALGORITHM])


def decode_token(token: str) -> dict:
    """
    Try local JWT first, then Supabase JWT.
    This allows both dev tokens and production Supabase tokens.
    """
    try:
        return _decode_local_jwt(token)
    except JWTError:
        pass
    try:
        return _decode_supabase_jwt(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FASTAPI DEPENDENCIES ──────────────────────────────────────────────────────

async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme)
    ],
) -> User:
    """
    Dependency: require a valid JWT. Raises 401 if missing or invalid.
    Use on any protected endpoint.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)

    user_id = payload.get("sub")
    email   = payload.get("email", "")
    tier    = payload.get("tier", "free")

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    return User(id=user_id, email=email, tier=tier)


async def optional_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme)
    ],
) -> User | None:
    """
    Dependency: user is optional. Returns None if no token provided.
    Use on endpoints that work for both authenticated and anonymous users.
    """
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None


def require_researcher(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Dependency: require researcher or admin tier."""
    if not user.is_researcher:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Researcher tier required",
        )
    return user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Dependency: require admin tier."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


# ── RATE LIMITER ──────────────────────────────────────────────────────────────

class RateLimiter:
    """
    Simple Redis-backed rate limiter.
    Tracks monthly query counts per user.
    """

    def __init__(self):
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                settings.REDIS_URL, decode_responses=True
            )
        return self._redis

    async def check_and_increment(self, user: User, action: str = "query") -> bool:
        """
        Returns True if the action is allowed.
        Returns False if the monthly limit is exceeded.
        """
        limit = user.monthly_query_limit
        if limit is None:
            return True   # unlimited

        r = await self._get_redis()
        month_key = datetime.utcnow().strftime("%Y-%m")
        key = f"ratelimit:{user.id}:{action}:{month_key}"

        count = await r.incr(key)
        if count == 1:
            # Set TTL to expire at end of month (32 days, safe)
            await r.expire(key, 32 * 24 * 3600)

        if count > limit:
            await r.decr(key)  # Roll back the increment
            return False

        return True

    async def get_usage(self, user: User, action: str = "query") -> dict:
        """Return current usage stats for a user."""
        limit = user.monthly_query_limit
        r = await self._get_redis()
        month_key = datetime.utcnow().strftime("%Y-%m")
        key = f"ratelimit:{user.id}:{action}:{month_key}"
        count = int(await r.get(key) or 0)
        return {
            "used":      count,
            "limit":     limit,
            "remaining": None if limit is None else max(0, limit - count),
            "resets_at": (datetime.utcnow().replace(day=1) + timedelta(days=32)).replace(day=1).isoformat(),
        }


rate_limiter = RateLimiter()
