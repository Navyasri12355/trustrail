from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from backend.db.database import engine
from backend.db import models
from backend.routes.manifest       import router as manifest_router
from backend.routes.mandates       import router as mandates_router
from backend.routes.pay            import router as pay_router
from backend.routes.audit_log      import router as audit_router
from backend.routes.merchants      import router as merchants_router
from backend.adapters.ucp          import router as ucp_router
from backend.adapters.ap2          import router as ap2_router
from backend.adapters.uap_ready    import router as uap_router

load_dotenv()

# Auto-create tables on startup
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="TrustRail API",
    description="Protocol-agnostic mandate & guardrail layer for agentic commerce",
    version="0.4.0",
)

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
app.include_router(audit_router)      # Story-08: GET /audit-log
app.include_router(merchants_router)  # Multi-tenant: POST/GET/PUT/DELETE /merchants
app.include_router(ucp_router)        # Story-10: POST /adapters/ucp/checkout
app.include_router(ap2_router)        # Story-11: POST /adapters/ap2/intent
app.include_router(uap_router)        # Story-12: POST /adapters/uap/intent (functional, Ed25519 stand-in)


@app.get("/health")
def health():
    return {"status": "ok", "service": "TrustRail API", "version": "0.4.0"}
