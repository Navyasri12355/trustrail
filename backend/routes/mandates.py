"""
Story-04: Mandate issuance API   — POST /mandates
Story-05: Mandate revocation API — DELETE /mandates/{mandate_id}
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from backend.crypto.keys import sign_payload
from backend.db.database import get_db
from backend.db.models import Mandate, Merchant
from backend.dependencies.tenant import get_merchant_from_header

router = APIRouter(prefix="/mandates", tags=["mandates"])
limiter = Limiter(key_func=get_remote_address)


# ── Request / Response schemas ───────────────────────────────────────────────

class MandateScope(BaseModel):
    allowed_categories:  list[str] = Field(..., example=["groceries", "household"])
    max_per_transaction: float     = Field(..., gt=0, example=500.0)
    max_rolling_7d:      float     = Field(..., gt=0, example=2000.0)
    currency:            str       = Field(default="INR")


class CreateMandateRequest(BaseModel):
    issuer_user_id:  str          = Field(..., example="usr_123")
    agent_id:        str          = Field(..., example="agent_abc")
    scope:           MandateScope
    expires_in_days: int          = Field(default=30, ge=1, le=365)
    protocol_origin: str          = Field(default="internal",
                                          example="ap2 | ucp | uap_ready | internal")


class MandateResponse(BaseModel):
    mandate_id:      str
    issuer_user_id:  str
    agent_id:        str
    merchant_id:     str
    scope:           dict
    issued_at:       str
    expires_at:      str
    revoked:         bool
    signature:       str
    protocol_origin: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mandate_to_response(m: Mandate) -> MandateResponse:
    return MandateResponse(
        mandate_id=m.mandate_id,
        issuer_user_id=m.issuer_user_id,
        agent_id=m.agent_id,
        merchant_id=m.merchant_id,
        scope={
            "allowed_categories":  json.loads(m.allowed_categories),
            "max_per_transaction": m.max_per_transaction,
            "max_rolling_7d":      m.max_rolling_7d,
            "currency":            m.currency,
        },
        issued_at=m.issued_at.isoformat() + "Z",
        expires_at=m.expires_at.isoformat() + "Z",
        revoked=m.revoked,
        signature=m.signature,
        protocol_origin=m.protocol_origin,
    )


def _build_signable_payload(
    mandate_id: str,
    issuer_user_id: str,
    agent_id: str,
    merchant_id: str,
    scope: dict,
    issued_at: datetime,
    expires_at: datetime,
    protocol_origin: str,
) -> bytes:
    """Canonical payload to sign — deterministic JSON, no signature field."""
    payload = {
        "mandate_id":     mandate_id,
        "issuer_user_id": issuer_user_id,
        "agent_id":       agent_id,
        "merchant_id":    merchant_id,
        "scope":          scope,
        "issued_at":      issued_at.isoformat() + "Z",
        "expires_at":     expires_at.isoformat() + "Z",
        "protocol_origin": protocol_origin,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("", status_code=201, response_model=MandateResponse)
@limiter.limit("50/minute")  # Rate limit: 50 requests per minute per IP
def create_mandate(
    body: CreateMandateRequest,
    merchant: Merchant = Depends(get_merchant_from_header),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """
    Story-04: Issue a new signed mandate.
    Generates mandate_id, signs the payload with Ed25519, persists to DB.
    Rate limited: 50 requests per minute per IP.
    """
    mandate_id = "mnd_" + str(uuid.uuid4()).replace("-", "")
    now        = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=body.expires_in_days)

    scope_dict = {
        "allowed_categories":  body.scope.allowed_categories,
        "max_per_transaction": body.scope.max_per_transaction,
        "max_rolling_7d":      body.scope.max_rolling_7d,
        "currency":            body.scope.currency,
    }

    payload_bytes = _build_signable_payload(
        mandate_id=mandate_id,
        issuer_user_id=body.issuer_user_id,
        agent_id=body.agent_id,
        merchant_id=merchant.merchant_id,
        scope=scope_dict,
        issued_at=now,
        expires_at=expires_at,
        protocol_origin=body.protocol_origin,
    )

    try:
        signature = sign_payload(payload_bytes)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    mandate = Mandate(
        mandate_id=mandate_id,
        issuer_user_id=body.issuer_user_id,
        agent_id=body.agent_id,
        merchant_id=merchant.merchant_id,
        allowed_categories=json.dumps(body.scope.allowed_categories),
        max_per_transaction=body.scope.max_per_transaction,
        max_rolling_7d=body.scope.max_rolling_7d,
        currency=merchant.currency,
        issued_at=now,
        expires_at=expires_at,
        revoked=False,
        signature=signature,
        protocol_origin=body.protocol_origin,
    )

    db.add(mandate)
    db.commit()
    db.refresh(mandate)

    # Log mandate issuance to audit trail
    from backend.guardrail import audit as audit_writer
    audit_writer.log_mandate_event(
        db=db,
        mandate_id=mandate_id,
        merchant_id=merchant.merchant_id,
        event_type="mandate_issued"
    )

    return _mandate_to_response(mandate)


@router.get("/{mandate_id}", response_model=MandateResponse)
def get_mandate(
    mandate_id: str,
    merchant: Merchant = Depends(get_merchant_from_header),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """Fetch a mandate by ID. Enforces tenant isolation."""
    mandate = db.query(Mandate).filter(
        Mandate.mandate_id == mandate_id,
        Mandate.merchant_id == merchant.merchant_id
    ).first()
    if not mandate:
        raise HTTPException(status_code=404, detail="Mandate not found")
    return _mandate_to_response(mandate)


@router.delete("/{mandate_id}", status_code=200)
def revoke_mandate(
    mandate_id: str,
    merchant: Merchant = Depends(get_merchant_from_header),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """
    Story-05: Revoke a mandate — sets revoked=True.
    Subsequent guardrail checks on this mandate will BLOCK with reason 'revoked'.
    Enforces tenant isolation.
    """
    mandate = db.query(Mandate).filter(
        Mandate.mandate_id == mandate_id,
        Mandate.merchant_id == merchant.merchant_id
    ).first()
    if not mandate:
        raise HTTPException(status_code=404, detail="Mandate not found")

    mandate.revoked = True
    db.commit()

    # Log mandate revocation to audit trail
    from backend.guardrail import audit as audit_writer
    audit_writer.log_mandate_event(
        db=db,
        mandate_id=mandate_id,
        merchant_id=merchant.merchant_id,
        event_type="mandate_revoked"
    )

    return {"mandate_id": mandate_id, "revoked": True, "message": "Mandate revoked successfully"}
