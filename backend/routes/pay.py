"""
Story-09: POST /pay — the main payment flow.

Flow:
  1. Load mandate from DB
  2. Query audit log for spent_7d and seen_nonces
  3. Run guardrail engine (all 7 rules)
  4. Log decision to audit trail (always)
  5a. ALLOW → call Razorpay test-mode Orders API, return order details
  5b. BLOCK → return 402 with structured refusal + full rules checklist
"""

import json
from datetime import datetime, timedelta, timezone

import razorpay
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import AuditLog, Mandate, Merchant
from backend.dependencies.tenant import get_merchant_from_header
from backend.guardrail import audit as audit_writer
from backend.guardrail.engine import MandateData, PaymentRequest, validate

router = APIRouter(tags=["payments"])
limiter = Limiter(key_func=get_remote_address)


# ── Razorpay client ───────────────────────────────────────────────────────────


def _get_razorpay_client(merchant: Merchant):
    """Get Razorpay client with merchant-specific credentials."""
    key_id = merchant.razorpay_key_id
    key_secret = merchant.razorpay_key_secret
    if not key_id or not key_secret:
        raise HTTPException(
            status_code=500, detail="Razorpay credentials not configured for merchant"
        )
    return razorpay.Client(auth=(key_id, key_secret))


# ── Request / Response schemas ────────────────────────────────────────────────


class PayRequest(BaseModel):
    mandate_id: str = Field(..., example="mnd_abc123")
    amount: float = Field(..., gt=0, example=499.0)
    category: str = Field(..., example="groceries")
    nonce: str = Field(..., example="nonce_unique_per_request_001")


class RuleResultOut(BaseModel):
    rule: str
    passed: bool
    reason: str


class PayResponse(BaseModel):
    allowed: bool
    primary_reason: str
    rules: list[RuleResultOut]
    razorpay_order_id: str = None
    execution_token: str = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_mandate_data(mandate: Mandate) -> MandateData:
    return MandateData(
        mandate_id=mandate.mandate_id,
        issuer_user_id=mandate.issuer_user_id,
        agent_id=mandate.agent_id,
        merchant_id=mandate.merchant_id,
        allowed_categories=json.loads(mandate.allowed_categories),
        max_per_transaction=mandate.max_per_transaction,
        max_rolling_7d=mandate.max_rolling_7d,
        currency=mandate.currency,
        issued_at=mandate.issued_at,
        expires_at=mandate.expires_at,
        revoked=mandate.revoked,
        signature=mandate.signature,
        protocol_origin=mandate.protocol_origin,
    )


def _get_spent_7d(db: Session, mandate_id: str, merchant_id: str) -> float:
    """Sum of approved payments for this mandate in the trailing 7 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    result = (
        db.query(func.sum(AuditLog.amount))
        .filter(
            AuditLog.mandate_id == mandate_id,
            AuditLog.merchant_id == merchant_id,
            AuditLog.decision == "ALLOW",
            AuditLog.created_at >= cutoff,
        )
        .scalar()
    )
    return float(result or 0.0)


def _get_seen_nonces(db: Session, mandate_id: str, merchant_id: str) -> list[str]:
    """All nonces ever used under this mandate."""
    rows = (
        db.query(AuditLog.nonce)
        .filter(
            AuditLog.mandate_id == mandate_id,
            AuditLog.merchant_id == merchant_id,
            AuditLog.nonce.isnot(None),
        )
        .all()
    )
    return [r.nonce for r in rows]


# ── Route ─────────────────────────────────────────────────────────────────────


@router.post("/pay", response_model=PayResponse)
@limiter.limit("100/minute")  # Rate limit: 100 requests per minute per IP
def pay(
    body: PayRequest,
    merchant: Merchant = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
):
    """
    Story-09: Agent-initiated payment request.
    Always logs to audit trail — whether ALLOW or BLOCK.
    Enforces tenant isolation.
    Rate limited: 100 requests per minute per IP.
    """
    # 1. Load mandate with tenant isolation
    mandate_row = (
        db.query(Mandate)
        .filter(
            Mandate.mandate_id == body.mandate_id,
            Mandate.merchant_id == merchant.merchant_id,
        )
        .first()
    )
    if not mandate_row:
        raise HTTPException(status_code=404, detail="Mandate not found")

    mandate_data = _load_mandate_data(mandate_row)

    # 2. Query history for rolling cap + replay detection
    spent_7d = _get_spent_7d(db, body.mandate_id, merchant.merchant_id)
    seen_nonces = _get_seen_nonces(db, body.mandate_id, merchant.merchant_id)

    payment_req = PaymentRequest(
        mandate_id=body.mandate_id,
        amount=body.amount,
        category=body.category,
        nonce=body.nonce,
        agent_id=mandate_data.agent_id,
    )

    # 3. Run ALL 7 guardrail rules
    decision = validate(
        mandate=mandate_data,
        request=payment_req,
        spent_7d=spent_7d,
        seen_nonces=seen_nonces,
    )

    # 4. Log to immutable audit trail (always — ALLOW and BLOCK)
    audit_writer.log_guardrail_decision(
        db=db,
        mandate_id=body.mandate_id,
        merchant_id=merchant.merchant_id,
        decision=decision,
        amount=body.amount,
        category=body.category,
        nonce=body.nonce,
    )

    rules_out = [
        RuleResultOut(rule=r.rule, passed=r.passed, reason=r.reason)
        for r in decision.rules
    ]

    # 5a. BLOCK — structured refusal
    if not decision.allowed:
        return PayResponse(
            allowed=False,
            primary_reason=decision.primary_reason,
            rules=rules_out,
        )

    # 5b. ALLOW — call Razorpay test-mode Orders API
    try:
        rz = _get_razorpay_client(merchant)
        # Razorpay amounts are in paise (INR × 100)
        order = rz.order.create(
            {
                "amount": int(body.amount * 100),
                "currency": merchant.currency,
                "receipt": f"tr_{body.nonce[:20]}",
                "notes": {
                    "mandate_id": body.mandate_id,
                    "agent_id": mandate_data.agent_id,
                    "category": body.category,
                    "execution_token": decision.execution_token,
                    "merchant_id": merchant.merchant_id,
                },
            }
        )
        razorpay_order_id = order["id"]
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Razorpay error: {exc!s}")

    return PayResponse(
        allowed=True,
        primary_reason="all_passed",
        rules=rules_out,
        razorpay_order_id=razorpay_order_id,
        execution_token=decision.execution_token,
    )
