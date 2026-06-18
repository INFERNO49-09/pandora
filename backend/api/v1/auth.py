"""
Auth API endpoints.

POST /auth/register  — create account
POST /auth/token     — login, get JWT
GET  /auth/me        — current user profile + usage
POST /auth/api-key   — generate API key (researcher tier)
DELETE /auth/api-key — revoke API key
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from auth.middleware import (
    User,
    create_access_token,
    get_current_user,
    hash_password,
    rate_limiter,
    require_researcher,
    verify_password,
)
from core.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])


# ── REQUEST / RESPONSE MODELS ─────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str | None = None
    institution: str | None = None
    research_domains: list[str] = []
    tier: str = "free"


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    tier: str
    expires_in: int = 60 * 24 * 7 * 60   # seconds


class UserProfile(BaseModel):
    id: str
    email: str
    full_name: str | None
    institution: str | None
    research_domains: list[str]
    tier: str
    created_at: str
    usage: dict


# ── DB HELPERS ────────────────────────────────────────────────────────────────

async def _get_conn() -> asyncpg.Connection:
    dsn = settings.POSTGRES_DSN.replace("+asyncpg", "")
    return await asyncpg.connect(dsn)


async def _get_user_by_email(email: str) -> dict | None:
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM pandora_users WHERE email = $1", email
        )
        return dict(row) if row else None
    finally:
        await conn.close()


async def _create_user(data: RegisterRequest) -> str:
    """Insert a new user. Returns user_id."""
    user_id = str(uuid.uuid4())
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO pandora_users
              (id, email, password_hash, full_name, institution,
               research_domains, tier, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
            """,
            user_id,
            data.email.lower().strip(),
            hash_password(data.password),
            data.full_name,
            data.institution,
            data.research_domains,
            data.tier,
        )
    finally:
        await conn.close()
    return user_id


# ── ENDPOINTS ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(req: RegisterRequest):
    """Create a new account."""
    existing = await _get_user_by_email(req.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user_id = await _create_user(req)
    token   = create_access_token(
        user_id=user_id,
        email=req.email.lower(),
        tier=req.tier,
    )
    return TokenResponse(
        access_token=token,
        user_id=user_id,
        email=req.email.lower(),
        tier=req.tier,
    )


@router.post("/token", response_model=TokenResponse)
async def login(req: LoginRequest):
    """Login and receive a JWT."""
    user = await _get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        tier=user["tier"],
    )
    return TokenResponse(
        access_token=token,
        user_id=user["id"],
        email=user["email"],
        tier=user["tier"],
    )


@router.get("/me", response_model=UserProfile)
async def get_me(current_user: Annotated[User, Depends(get_current_user)]):
    """Return current user profile + monthly usage."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM pandora_users WHERE id = $1", current_user.id
        )
    finally:
        await conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    usage = await rate_limiter.get_usage(current_user, "query")

    return UserProfile(
        id=row["id"],
        email=row["email"],
        full_name=row.get("full_name"),
        institution=row.get("institution"),
        research_domains=list(row.get("research_domains") or []),
        tier=row["tier"],
        created_at=str(row["created_at"]),
        usage=usage,
    )


@router.post("/api-key")
async def generate_api_key(
    current_user: Annotated[User, Depends(require_researcher)],
):
    """Generate a long-lived API key (researcher+ only)."""
    raw_key   = f"pnd_{secrets.token_urlsafe(32)}"
    key_hash  = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]

    conn = await _get_conn()
    try:
        # Revoke any existing key first
        await conn.execute(
            "DELETE FROM api_keys WHERE user_id = $1", current_user.id
        )
        await conn.execute(
            """
            INSERT INTO api_keys (user_id, key_hash, key_prefix, created_at)
            VALUES ($1, $2, $3, NOW())
            """,
            current_user.id, key_hash, key_prefix,
        )
    finally:
        await conn.close()

    return {
        "api_key":    raw_key,
        "key_prefix": key_prefix,
        "note":       "Store this key securely — it won't be shown again.",
        "usage":      "Pass as header: X-API-Key: <your-key>",
    }


@router.delete("/api-key", status_code=204)
async def revoke_api_key(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Revoke the current API key."""
    conn = await _get_conn()
    try:
        await conn.execute(
            "DELETE FROM api_keys WHERE user_id = $1", current_user.id
        )
    finally:
        await conn.close()
