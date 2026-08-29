"""
Authentication routes for dashboard access.
POST /auth/login - Issue JWT token for admin access
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.auth.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    DEFAULT_ADMIN_USERNAME,
    admin_password_matches,
    create_access_token,
    verify_token,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
security = HTTPBearer()
limiter = Limiter(key_func=get_remote_address)


# ── Request / Response schemas ───────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str = Field(..., example="admin")
    password: str = Field(..., example="your-dashboard-password")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest):
    """
    Authenticate admin user and issue JWT token.
    Credentials come from DASHBOARD_ADMIN_USERNAME / DASHBOARD_ADMIN_PASSWORD.
    Rate limited: 10 attempts per minute per IP to prevent brute force.
    """
    # Same generic error for both fields so enumeration is harder.
    # Always hash-check the password so username enumeration isn't cheaper than a guess.
    password_ok = admin_password_matches(body.password)
    if body.username != DEFAULT_ADMIN_USERNAME or not password_ok:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    access_token = create_access_token(data={"sub": body.username, "role": "admin"})

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
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


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
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
