import logging

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth.auth import validate_auth_config
from backend.db.database import engine, get_db
from backend.db import models
from backend.routes.manifest       import router as manifest_router
from backend.routes.mandates       import router as mandates_router
from backend.routes.pay            import router as pay_router
from backend.routes.audit_log      import router as audit_router
from backend.routes.merchants      import router as merchants_router
from backend.routes.auth           import router as auth_router
from backend.adapters.ucp          import router as ucp_router
from backend.adapters.ap2          import router as ap2_router
from backend.adapters.uap_ready    import router as uap_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# Auto-create tables on startup
models.Base.metadata.create_all(bind=engine)
validate_auth_config()

# Rate limiting setup
limiter = Limiter(key_func=get_remote_address)

def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"}
    )

app = FastAPI(
    title="TrustRail API",
    description="Protocol-agnostic mandate & guardrail layer for agentic commerce",
    version="0.5.0",
    state=limiter
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(manifest_router)   # Story-02: GET /.well-known/ucp
app.include_router(mandates_router)   # Story-04/05: POST /mandates, DELETE /mandates/{id}
app.include_router(pay_router)        # Story-09: POST /pay
app.include_router(audit_router)      # Story-08: GET /audit-log · GET /audit-log/verify
app.include_router(merchants_router)  # Multi-tenant: POST/GET/PUT/DELETE /merchants
app.include_router(auth_router)       # Authentication: POST /auth/login, /auth/verify
app.include_router(ucp_router)        # Story-10: POST /adapters/ucp/checkout
app.include_router(ap2_router)        # Story-11: POST /adapters/ap2/intent
app.include_router(uap_router)        # Story-12: POST /adapters/uap/intent (functional, Ed25519 stand-in)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    """Liveness + DB ping. Returns 200 with status=degraded if the database is down."""
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unreachable"
    overall = "ok" if db_status == "ok" else "degraded"
    return {
        "status": overall,
        "database": db_status,
        "service": "TrustRail API",
        "version": "0.5.0",
    }
