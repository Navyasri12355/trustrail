"""
Authentication routes for dashboard access.
POST /auth/login - Issue JWT token for admin access
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import Optional
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.auth.auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    verify_token,
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_ADMIN_PASSWORD,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

router = APIRouter(prefix="/auth", tags=["authentication"])
security = HTTPBearer()
limiter = Limiter(key_func=get_remote_address)


# ── Request / Response schemas ───────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str = Field(..., example="admin")
    password: str = Field(..., example="admin123")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")  # Rate limit: 10 login attempts per minute per IP
def login(body: LoginRequest):
    """
    Authenticate admin user and issue JWT token.
    Uses default credentials from environment variables.
    Rate limited: 10 attempts per minute per IP to prevent brute force.
    """
    # Verify credentials (demo mode - in production, check database)
    if body.username != DEFAULT_ADMIN_USERNAME:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    # For demo, we compare plain passwords. In production, use hashed passwords
    if body.password != DEFAULT_ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    # Create access token
    access_token = create_access_token(
        data={"sub": body.username, "role": "admin"}
    )
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.post("/verify")
def verify_auth(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Verify if the provided JWT token is valid.
    Used by the frontend to check authentication status.
    """
    token = credentials.credentials
    payload = verify_token(token)
    
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return {"valid": True, "username": payload.get("sub"), "role": payload.get("role")}


# ── Dependency for protected routes ───────────────────────────────────────────

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Dependency to protect routes that require authentication.
    Returns the user payload if token is valid, raises 401 otherwise.
    """
    token = credentials.credentials
    payload = verify_token(token)
    
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return payload
