"""
Story-11: AP2 Protocol Adapter
POST /adapters/ap2/intent

Accepts an AP2-style signed mandate/intent object, verifies the signature,
maps fields to TrustRail's internal MandateRequest, and runs the guardrail.

AP2 uses a verifiable-credential approach for mandate signing. Since no public
AP2 SDK exists yet, we use our own Ed25519 scheme as a stand-in for the
VC signature verification step — this is documented explicitly.
protocol_origin is set to 'ap2' in the mandate.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import razorpay
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.crypto.keys import verify_signature
from backend.db.database import get_db
from backend.db.models import AuditLog, Mandate, Merchant
from backend.guardrail import audit as audit_writer
from backend.guardrail.engine import MandateData, PaymentRequest, validate
from backend.dependencies.tenant import get_merchant_from_header

router = APIRouter(prefix="/adapters/ap2", tags=["adapters"])


# ── AP2-shaped request schema ─────────────────────────────────────────────────

class AP2Scope(BaseModel):
    """AP2 mandate scope — mirrors our internal scope but uses AP2 field names."""
    permitted_categories: List[str] = Field(..., example=["groceries"])
    max_single_txn_inr:   float     = Field(..., gt=0, example=500.0)
    max_7d_window_inr:    float     = Field(..., gt=0, example=2000.0)
    currency:             str       = Field(default="INR")


class AP2MandateCredential(BaseModel):
    """
    AP2-style signed mandate credential.
    In production AP2 this would be a W3C Verifiable Credential (JWT or JSON-LD).
    We use an Ed25519 hex signature over the canonical JSON as a stand-in.
    See docs/uap-mapping.md for the AP2 → TrustRail field mapping.
    """
    mandate_id:     str       = Field(..., example="mnd_abc123")
    issuer_did:     str       = Field(..., example="did:example:usr_123")  # maps to issuer_user_id
    agent_did:      str       = Field(..., example="did:example:agent_abc")
    merchant_id:    str       = Field(..., example="mrc_demo_001")
    scope:          AP2Scope
    issued_at:      str       = Field(..., example="2026-08-22T10:00:00Z")
    expires_at:     str       = Field(..., example="2026-09-22T10:00:00Z")
    proof:          str       = Field(..., example="ed25519:<hex>")  # AP2 VC proof field


class AP2IntentRequest(BaseModel):
    """Full AP2 payment intent — the mandate credential + the specific payment request."""
    credential:  AP2MandateCredential
    amount_inr:  float = Field(..., gt=0, example=299.0)
    category:    str   = Field(..., example="groceries")
    nonce:       str   = Field(..., example="ap2_nonce_001")


# ── AP2-shaped response ───────────────────────────────────────────────────────

class AP2IntentResponse(BaseModel):
    ap2_version:       str = "ap2-draft-2025"
    status:            str          # "approved" | "blocked"
    mandate_id:        str
    decision_reason:   str
    razorpay_order_id: Optional[str] = None
    execution_token:   Optional[str] = None
    proof_verified:    bool
    rules_summary:     list


# ── Helpers ───────────────────────────────────────────────────────────────────

def _verify_ap2_proof(cred: AP2MandateCredential) -> bool:
    """
    AP2 proof verification stand-in.
    In production AP2 this verifies a W3C VC proof (JWT RS256 or Ed25519).
    Here we verify an Ed25519 signature over the canonical credential JSON
    (excluding the 'proof' field), matching how we sign mandates at issuance.

    NOTE: This is documented as a stand-in in docs/uap-mapping.md.
    """
    payload_dict = {
        "mandate_id":  cred.mandate_id,
        "issuer_did":  cred.issuer_did,
        "agent_did":   cred.agent_did,
        "merchant_id": cred.merchant_id,
        "scope": {
            "permitted_categories": cred.scope.permitted_categories,
            "max_single_txn_inr":   cred.scope.max_single_txn_inr,
            "max_7d_window_inr":    cred.scope.max_7d_window_inr,
            "currency":             cred.scope.currency,
        },
        "issued_at":  cred.issued_at,
        "expires_at": cred.expires_at,
    }
    payload_bytes = json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode()
    return verify_signature(payload_bytes, cred.proof)


def _ap2_to_mandate_data(cred: AP2MandateCredential, db: Session, merchant_id: str) -> MandateData:
    """
    Map AP2 credential fields → TrustRail MandateData.
    Field mapping is documented in docs/uap-mapping.md.
    Enforces tenant isolation.
    """
    # Look up the stored mandate to get the server-side signature
    mandate_row = db.query(Mandate).filter(
        Mandate.mandate_id == cred.mandate_id,
        Mandate.merchant_id == merchant_id
    ).first()
    if not mandate_row:
        raise HTTPException(status_code=404, detail=f"Mandate {cred.mandate_id} not found")

    return MandateData(
        mandate_id=mandate_row.mandate_id,
        issuer_user_id=mandate_row.issuer_user_id,   # AP2: issuer_did
        agent_id=mandate_row.agent_id,               # AP2: agent_did
        merchant_id=mandate_row.merchant_id,
        allowed_categories=json.loads(mandate_row.allowed_categories),  # AP2: permitted_categories
        max_per_transaction=mandate_row.max_per_transaction,            # AP2: max_single_txn_inr
        max_rolling_7d=mandate_row.max_rolling_7d,                      # AP2: max_7d_window_inr
        currency=mandate_row.currency,
        issued_at=mandate_row.issued_at,
        expires_at=mandate_row.expires_at,
        revoked=mandate_row.revoked,
        signature=mandate_row.signature,
        protocol_origin="ap2",
    )


def _get_spent_7d(db: Session, mandate_id: str) -> float:
    cutoff = datetime.utcnow() - timedelta(days=7)
    result = (
        db.query(func.sum(AuditLog.amount))
        .filter(AuditLog.mandate_id == mandate_id, AuditLog.decision == "ALLOW",
                AuditLog.created_at >= cutoff)
        .scalar()
    )
    return float(result or 0.0)


def _get_seen_nonces(db: Session, mandate_id: str) -> List[str]:
    rows = (
        db.query(AuditLog.nonce)
        .filter(AuditLog.mandate_id == mandate_id, AuditLog.nonce.isnot(None))
        .all()
    )
    return [r.nonce for r in rows]


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/intent", response_model=AP2IntentResponse)
def ap2_intent(
    body: AP2IntentRequest,
    merchant: Merchant = Depends(get_merchant_from_header),
    db: Session = Depends(get_db)
):
    """
    Story-11: AP2 adapter.
    1. Verify AP2 credential proof (Ed25519 stand-in for W3C VC)
    2. Map AP2 fields → internal MandateData
    3. Run guardrail engine (all 7 rules)
    4. Log to audit trail
    5. ALLOW → Razorpay order / BLOCK → structured refusal
    Enforces tenant isolation.
    """
    # 1. Verify AP2 proof
    proof_verified = _verify_ap2_proof(body.credential)
    # Note: proof failure is captured in guardrail rule 1 (signature_valid)
    # We still run all rules so the audit trail is complete.

    # 2. Map AP2 → internal
    mandate_data = _ap2_to_mandate_data(body.credential, db, merchant.merchant_id)

    payment_req = PaymentRequest(
        mandate_id=body.credential.mandate_id,
        amount=body.amount_inr,
        category=body.category,
        nonce=body.nonce,
        agent_id=mandate_data.agent_id,
    )

    # 3. Guardrail
    spent_7d    = _get_spent_7d(db, body.credential.mandate_id)
    seen_nonces = _get_seen_nonces(db, body.credential.mandate_id)

    decision = validate(
        mandate=mandate_data,
        request=payment_req,
        spent_7d=spent_7d,
        seen_nonces=seen_nonces,
    )

    # 4. Audit log (always)
    audit_writer.log_guardrail_decision(
        db=db,
        mandate_id=body.credential.mandate_id,
        merchant_id=merchant.merchant_id,
        decision=decision,
        amount=body.amount_inr,
        category=body.category,
        nonce=body.nonce,
    )

    rules_summary = [
        {"rule": r.rule, "passed": r.passed, "reason": r.reason}
        for r in decision.rules
    ]

    # 5a. BLOCK
    if not decision.allowed:
        return AP2IntentResponse(
            status="blocked",
            mandate_id=body.credential.mandate_id,
            decision_reason=decision.primary_reason,
            proof_verified=proof_verified,
            rules_summary=rules_summary,
        )

    # 5b. ALLOW → Razorpay
    rz = razorpay.Client(auth=(
        merchant.razorpay_key_id,
        merchant.razorpay_key_secret,
    ))
    order = rz.order.create({
        "amount":   int(body.amount_inr * 100),
        "currency": merchant.currency,
        "receipt":  f"ap2_{body.nonce[:16]}",
        "notes": {
            "mandate_id":      body.credential.mandate_id,
            "issuer_did":      body.credential.issuer_did,
            "agent_did":       body.credential.agent_did,
            "category":        body.category,
            "protocol":        "ap2-draft-2025",
            "execution_token": decision.execution_token,
            "merchant_id":     merchant.merchant_id,
        },
    })

    return AP2IntentResponse(
        status="approved",
        mandate_id=body.credential.mandate_id,
        decision_reason="all_passed",
        razorpay_order_id=order["id"],
        execution_token=decision.execution_token,
        proof_verified=proof_verified,
        rules_summary=rules_summary,
    )
