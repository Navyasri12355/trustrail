"""
Story-10: UCP Protocol Adapter
POST /adapters/ucp/checkout

Maps an incoming UCP-style checkout call into TrustRail's internal
MandateRequest format, runs the guardrail, and returns a UCP-compatible response.
Adapter is intentionally thin — zero business logic, just shape translation.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional
import json
from datetime import datetime, timedelta

from backend.db.database import get_db
from backend.db.models import Mandate, AuditLog, Merchant
from backend.guardrail.engine import MandateData, PaymentRequest, validate
from backend.guardrail import audit as audit_writer
from backend.dependencies.tenant import get_merchant_from_header
from sqlalchemy import func

router = APIRouter(prefix="/adapters/ucp", tags=["adapters"])


# ── UCP-shaped request schema ─────────────────────────────────────────────────

class UCPBuyerAgent(BaseModel):
    agent_id:  str = Field(..., example="agent_shopping_bot_v1")
    user_id:   str = Field(..., example="usr_123")


class UCPCatalogItem(BaseModel):
    category:    str   = Field(..., example="groceries")
    item_name:   str   = Field(..., example="Organic Oats 1kg")
    amount_inr:  float = Field(..., gt=0, example=299.0)


class UCPCheckoutRequest(BaseModel):
    """UCP-style checkout call shape."""
    mandate_id:  str          = Field(..., example="mnd_abc123")
    buyer_agent: UCPBuyerAgent
    item:        UCPCatalogItem
    nonce:       str          = Field(..., example="ucp_nonce_001")
    merchant_id: Optional[str] = None


# ── UCP-shaped response schema ────────────────────────────────────────────────

class UCPCheckoutResponse(BaseModel):
    status:            str          # "approved" | "blocked"
    ucp_version:       str = "ucp-1.0"
    mandate_id:        str
    decision_reason:   str
    razorpay_order_id: Optional[str] = None
    execution_token:   Optional[str] = None
    rules_summary:     list


# ── Helpers (shared with pay.py — avoid circular import by inlining) ──────────

def _load_mandate(db: Session, mandate_id: str, merchant_id: str) -> Mandate:
    m = db.query(Mandate).filter(
        Mandate.mandate_id == mandate_id,
        Mandate.merchant_id == merchant_id
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail=f"Mandate {mandate_id} not found")
    return m


def _to_mandate_data(m: Mandate) -> MandateData:
    return MandateData(
        mandate_id=m.mandate_id,
        issuer_user_id=m.issuer_user_id,
        agent_id=m.agent_id,
        merchant_id=m.merchant_id,
        allowed_categories=json.loads(m.allowed_categories),
        max_per_transaction=m.max_per_transaction,
        max_rolling_7d=m.max_rolling_7d,
        currency=m.currency,
        issued_at=m.issued_at,
        expires_at=m.expires_at,
        revoked=m.revoked,
        signature=m.signature,
        protocol_origin=m.protocol_origin,
    )


def _get_spent_7d(db: Session, mandate_id: str) -> float:
    cutoff = datetime.utcnow() - timedelta(days=7)
    result = (
        db.query(func.sum(AuditLog.amount))
        .filter(
            AuditLog.mandate_id == mandate_id,
            AuditLog.decision   == "ALLOW",
            AuditLog.created_at >= cutoff,
        )
        .scalar()
    )
    return float(result or 0.0)


def _get_seen_nonces(db: Session, mandate_id: str):
    rows = (
        db.query(AuditLog.nonce)
        .filter(AuditLog.mandate_id == mandate_id, AuditLog.nonce.isnot(None))
        .all()
    )
    return [r.nonce for r in rows]


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/checkout", response_model=UCPCheckoutResponse)
def ucp_checkout(
    body: UCPCheckoutRequest,
    merchant: Merchant = Depends(get_merchant_from_header),
    db: Session = Depends(get_db)
):
    """
    Story-10: UCP adapter.
    Translates UCP checkout payload → internal MandateRequest → guardrail → response.
    protocol_origin will be 'ucp' in audit log.
    Enforces tenant isolation.
    """
    # ── Shape translation (UCP → internal) ───────────────────────────────────
    mandate_row  = _load_mandate(db, body.mandate_id, merchant.merchant_id)
    mandate_data = _to_mandate_data(mandate_row)

    payment_req = PaymentRequest(
        mandate_id=body.mandate_id,
        amount=body.item.amount_inr,
        category=body.item.category,
        nonce=body.nonce,
        agent_id=body.buyer_agent.agent_id,
    )

    # ── Guardrail ─────────────────────────────────────────────────────────────
    spent_7d    = _get_spent_7d(db, body.mandate_id)
    seen_nonces = _get_seen_nonces(db, body.mandate_id)

    decision = validate(
        mandate=mandate_data,
        request=payment_req,
        spent_7d=spent_7d,
        seen_nonces=seen_nonces,
    )

    audit_writer.log_guardrail_decision(
        db=db,
        mandate_id=body.mandate_id,
        merchant_id=merchant.merchant_id,
        decision=decision,
        amount=body.item.amount_inr,
        category=body.item.category,
        nonce=body.nonce,
    )

    rules_summary = [
        {"rule": r.rule, "passed": r.passed, "reason": r.reason}
        for r in decision.rules
    ]

    # ── BLOCK ─────────────────────────────────────────────────────────────────
    if not decision.allowed:
        return UCPCheckoutResponse(
            status="blocked",
            mandate_id=body.mandate_id,
            decision_reason=decision.primary_reason,
            rules_summary=rules_summary,
        )

    # ── ALLOW → Razorpay ──────────────────────────────────────────────────────
    import razorpay
    rz = razorpay.Client(auth=(
        merchant.razorpay_key_id,
        merchant.razorpay_key_secret,
    ))
    order = rz.order.create({
        "amount":   int(body.item.amount_inr * 100),
        "currency": merchant.currency,
        "receipt":  f"ucp_{body.nonce[:16]}",
        "notes": {
            "mandate_id":      body.mandate_id,
            "agent_id":        body.buyer_agent.agent_id,
            "category":        body.item.category,
            "protocol":        "ucp-1.0",
            "execution_token": decision.execution_token,
            "merchant_id":     merchant.merchant_id,
        },
    })

    return UCPCheckoutResponse(
        status="approved",
        mandate_id=body.mandate_id,
        decision_reason="all_passed",
        razorpay_order_id=order["id"],
        execution_token=decision.execution_token,
        rules_summary=rules_summary,
    )
