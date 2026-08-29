"""
Rate limiting middleware for TrustRail API.
Uses slowapi for token bucket rate limiting.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Create limiter instance
limiter = Limiter(key_func=get_remote_address)


# Custom rate limit exceeded handler
def custom_rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Custom handler for rate limit exceeded errors."""
    return {"detail": f"Rate limit exceeded: {exc.detail}", "status_code": 429}
