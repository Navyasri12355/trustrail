"""
Authentication module for TrustRail dashboard.
Provides JWT-based authentication for admin access.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

logger = logging.getLogger("trustrail.auth")

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT configuration
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Values that ship in .env.example — never allowed when TRUSTRAIL_ENV=production
_EXAMPLE_JWT_SECRET = "your-secret-key-change-in-production"
_EXAMPLE_ADMIN_PASSWORD = "admin123"


def _jwt_secret() -> str:
    return os.getenv("JWT_SECRET_KEY", _EXAMPLE_JWT_SECRET)


SECRET_KEY = _jwt_secret()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(tz=timezone.utc) + expires_delta
    else:
        expire = datetime.now(tz=timezone.utc) + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, _jwt_secret(), algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> dict | None:
    """Verify a JWT token and return the payload if valid."""
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


DEFAULT_ADMIN_USERNAME = os.getenv("DASHBOARD_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DASHBOARD_ADMIN_PASSWORD", _EXAMPLE_ADMIN_PASSWORD)


def _auth_config_issues() -> list:
    jwt_secret = _jwt_secret()
    password = os.getenv("DASHBOARD_ADMIN_PASSWORD", _EXAMPLE_ADMIN_PASSWORD)
    issues = []
    if not jwt_secret or jwt_secret == _EXAMPLE_JWT_SECRET or len(jwt_secret) < 32:
        issues.append(
            "JWT_SECRET_KEY is missing, shorter than 32 characters, or still the .env.example default"
        )
    if not password or password == _EXAMPLE_ADMIN_PASSWORD:
        issues.append(
            "DASHBOARD_ADMIN_PASSWORD is empty or still the .env.example default (admin123)"
        )
    return issues


def validate_auth_config() -> None:
    """
    Local/dev: warn and continue so Docker + .env.example still boot.
    TRUSTRAIL_ENV=production: refuse to start with example credentials.
    """
    env = os.getenv("TRUSTRAIL_ENV", "development").strip().lower()
    issues = _auth_config_issues()
    if not issues:
        return
    msg = "Insecure dashboard auth config: " + "; ".join(issues)
    if env == "production":
        raise RuntimeError(msg + ". Refusing to start with TRUSTRAIL_ENV=production.")
    logger.warning("%s Allowed because TRUSTRAIL_ENV=%s.", msg, env)


def admin_password_matches(plain_password: str) -> bool:
    """Constant-time-ish check against the env password (bcrypt)."""
    hashed = get_password_hash(
        os.getenv("DASHBOARD_ADMIN_PASSWORD", _EXAMPLE_ADMIN_PASSWORD)
    )
    return verify_password(plain_password, hashed)
