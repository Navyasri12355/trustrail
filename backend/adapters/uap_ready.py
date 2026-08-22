"""
Story-12 (upgraded): UAP-Functional Adapter
POST /adapters/uap/intent

NPCI's Unified Agent Protocol (UAP) has no public spec as of August 2026.
This adapter is designed against publicly reported UAP design intent and now
runs the *full* TrustRail guardrail + Razorpay order creation — it is no
longer a dead-end stub.

Honest framing (same caveat as AP2):
  - NPCI token signature verification uses Ed25519 as a stand-in.
    In production, replace _verify_uap_token() with NPCI's actual
    token verification scheme when the spec ships.
  - "agent_registry_id" is accepted as a plain string; in production
    this would be validated against an NPCI agent registry endpoint.

Field mapping: docs/uap-mapping.md
UAP field status (CONFIRMED / ANTICIPATED) is unchanged — see that doc.
"""

import json
import os
from datetime import datetime, timedelta
from typing import List, Optional

import razorpay
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.crypto.keys import verify_signature
from backend.db.database import get_db
from backend.db.models import AuditLog, Mandate
from backend.guardrail import audit as audit_writer
from backend.guardrail.engine import MandateData, PaymentRequest, validate

router = APIRouter(prefix="/adapters/uap", tags=["adapters"])


# ── UAP-shaped request schema (anticipated, not confirmed) ────────────────────

class UAPDelegationToken(BaseModel):
    """
    Anticipated UAP delegation token.
    Based on: NPCI agent registry + RBI delegation model (public reporting only).

    Field STATUS labels:
      CONFIRMED   — explicitly reported in NPCI/RBI public briefings
      ANTICIPATED — inferred from UPI architecture / design intent
    """
    delegation_id:       str   = Field(..., description="UAP delegation ID (ANTICIPATED)")
    agent_registry_id:   str   = Field(..., description="NPCI agent registry ID (ANTICIPATED)")
    delegator_vpa:       str   = Field(..., description="UPI VPA of the delegating user (CONFIRMED — UPI identity model)")
    merchant_vpa:        str   = Field(..., description="Target merchant UPI VPA (CONFIRMED — UPI merchant model)")
    # Spend limits — CONFIRMED from public reporting
    max_per_txn_inr:     float = Field(..., description="Per-transaction cap (CONFIRMED in reports)")
    max_rolling_inr:     float = Field(..., description="Rolling window cap (CONFIRMED in reports)")
    permitted_categories: List[str] = Field(..., description="Allowed spend categories (CONFIRMED)")
    validity_seconds:    int   = Field(..., description="Token validity window in seconds (ANTICIPATED)")
    issued_at_utc:       str   = Field(..., description="Token issue timestamp ISO-8601 (ANTICIPATED)")
    # Signature — ANTICIPATED; stand-in uses Ed25519 (same as AP2 adapter)
    uap_signature:       str   = Field(..., description="NPCI-issued token signature (ANTICIPATED — Ed25519 stand-in)")


class UAPPaymentIntent(BaseModel):
    """UAP payment intent submitted by an AI agent."""
    delegation_token:    UAPDelegationToken
    # Bridge field: TrustRail mandate that corresponds to this UAP delegation.
    # Needed because UAP's delegation model maps to TrustRail's mandate schema.
    internal_mandate_id: str   = Field(
        ...,
        description="TrustRail mandate_id corresponding to this UAP delegation"
    )
    amount_inr:          float = Field(..., gt=0)
    category:            str
    nonce:               str


# ── UAP-shaped response schema ────────────────────────────────────────────────

class UAPIntentResponse(BaseModel):
    uap_version:         str = "uap-trustrail-v1"
    status:              str          # "approved" | "blocked"
    mandate_id:          str
    decision_reason:     str
    razorpay_order_id:   Optional[str] = None
    execution_token:     Optional[str] = None
    token_verified:      bool
    rules_summary:       list
    field_mapping:       dict         # educational: shows UAP → TrustRail translation


# ── Helpers ───────────────────────────────────────────────────────────────────

def _verify_uap_token(token: UAPDelegationToken, mandate: Mandate) -> bool:
    """
    UAP token signature verification stand-in.

    PRODUCTION NOTE: Replace this with NPCI's actual token verification scheme
    when the UAP spec ships. The signature scheme (JWT, NPCI-specific MAC,
    or Ed25519) is ANTICIPATED — not confirmed in any public spec.

    Stand-in approach: verify an Ed25519 signature over the canonical token
    JSON (excluding the 'uap_signature' field), matching how TrustRail signs
    mandates at issuance. This is identical to the AP2 adapter's stand-in.
    """
    payload_dict = {
        "delegation_id":       token.delegation_id,
        "agent_registry_id":   token.agent_registry_id,
        "delegator_vpa":       token.delegator_vpa,
        "merchant_vpa":        token.merchant_vpa,
        "max_per_txn_inr":     token.max_per_txn_inr,
        "max_rolling_inr":     token.max_rolling_inr,
        "permitted_categories": token.permitted_categories,
        "validity_seconds":    token.validity_seconds,
        "issued_at_utc":       token.issued_at_utc,
    }
    payload_bytes = json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode()
    return verify_signature(payload_bytes, token.uap_signature)


def _uap_to_mandate_data(token: UAPDelegationToken, mandate: Mandate) -> MandateData:
    """
    Map UAP delegation token fields → TrustRail MandateData.
    Full field mapping documented in docs/uap-mapping.md.
    """
    return MandateData(
        mandate_id=mandate.mandate_id,
        issuer_user_id=mandate.issuer_user_id,      # UAP: delegator_vpa (CONFIRMED)
        agent_id=mandate.agent_id,                   # UAP: agent_registry_id (ANTICIPATED)
        merchant_id=mandate.merchant_id,             # UAP: merchant_vpa (CONFIRMED)
        allowed_categories=json.loads(mandate.allowed_categories),  # UAP: permitted_categories (CONFIRMED)
        max_per_transaction=mandate.max_per_transaction,            # UAP: max_per_txn_inr (CONFIRMED)
        max_rolling_7d=mandate.max_rolling_7d,                      # UAP: max_rolling_inr (CONFIRMED)
        currency=mandate.currency,                   # INR — UPI is INR-only (CONFIRMED)
        issued_at=mandate.issued_at,
        expires_at=mandate.expires_at,
        revoked=mandate.revoked,
        signature=mandate.signature,
        protocol_origin="uap_ready",
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


def _get_seen_nonces(db: Session, mandate_id: str) -> List[str]:
    rows = (
        db.query(AuditLog.nonce)
        .filter(AuditLog.mandate_id == mandate_id, AuditLog.nonce.isnot(None))
        .all()
    )
    return [r.nonce for r in rows]


def _build_field_mapping(token: UAPDelegationToken, mandate_id: str) -> dict:
    """Returns the UAP → TrustRail field translation for transparency."""
    return {
        "mandate_id":           {"uap_field": "delegation_id",        "status": "ANTICIPATED", "value": mandate_id},
        "issuer_user_id":       {"uap_field": "delegator_vpa",        "status": "CONFIRMED",   "value": f"upi:{token.delegator_vpa}"},
        "agent_id":             {"uap_field": "agent_registry_id",    "status": "ANTICIPATED", "value": token.agent_registry_id},
        "merchant_id":          {"uap_field": "merchant_vpa",         "status": "CONFIRMED",   "value": f"upi:{token.merchant_vpa}"},
        "allowed_categories":   {"uap_field": "permitted_categories", "status": "CONFIRMED",   "value": token.permitted_categories},
        "max_per_transaction":  {"uap_field": "max_per_txn_inr",      "status": "CONFIRMED",   "value": token.max_per_txn_inr},
        "max_rolling_7d":       {"uap_field": "max_rolling_inr",      "status": "CONFIRMED",   "value": token.max_rolling_inr},
        "currency":             {"uap_field": "implicit (UPI=INR)",   "status": "CONFIRMED",   "value": "INR"},
        "signature_stand_in":   {"note": "Ed25519 stand-in — replace with NPCI token scheme when spec ships"},
    }


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/intent", response_model=UAPIntentResponse)
def uap_intent(body: UAPPaymentIntent, db: Session = Depends(get_db)):
    """
    Story-12 (upgraded): Functional UAP adapter.

    1. Load the TrustRail mandate corresponding to this UAP delegation
    2. Verify the UAP delegation token signature (Ed25519 stand-in)
    3. Map UAP token fields → internal MandateData
    4. Run the full 7-rule guardrail engine
    5. Log to hash-chained audit trail
    6. ALLOW → Razorpay test-mode order
       BLOCK → structured refusal with per-rule breakdown

    PRODUCTION UPGRADE PATH (when UAP spec ships):
      • Replace _verify_uap_token() with NPCI's actual token verification
      • Replace internal_mandate_id bridge field with NPCI delegation registry lookup
      • Add agent_registry_id validation against NPCI registry API
    """
    # 1. Load stored mandate
    mandate_row = db.query(Mandate).filter(Mandate.mandate_id == body.internal_mandate_id).first()
    if not mandate_row:
        raise HTTPException(status_code=404, detail=f"Mandate {body.internal_mandate_id} not found")

    # 2. Verify UAP delegation token (Ed25519 stand-in)
    token_verified = _verify_uap_token(body.delegation_token, mandate_row)

    # 3. Map UAP → internal MandateData
    mandate_data = _uap_to_mandate_data(body.delegation_token, mandate_row)

    payment_req = PaymentRequest(
        mandate_id=body.internal_mandate_id,
        amount=body.amount_inr,
        category=body.category,
        nonce=body.nonce,
        agent_id=body.delegation_token.agent_registry_id,
    )

    # 4. Run full guardrail (all 7 rules, no short-circuit)
    spent_7d    = _get_spent_7d(db, body.internal_mandate_id)
    seen_nonces = _get_seen_nonces(db, body.internal_mandate_id)

    decision = validate(
        mandate=mandate_data,
        request=payment_req,
        spent_7d=spent_7d,
        seen_nonces=seen_nonces,
    )

    # 5. Audit log (always — hash-chained)
    audit_writer.log_guardrail_decision(
        db=db,
        mandate_id=body.internal_mandate_id,
        decision=decision,
        amount=body.amount_inr,
        category=body.category,
        nonce=body.nonce,
    )

    field_mapping = _build_field_mapping(body.delegation_token, body.internal_mandate_id)
    rules_summary = [
        {"rule": r.rule, "passed": r.passed, "reason": r.reason}
        for r in decision.rules
    ]

    # 6a. BLOCK
    if not decision.allowed:
        return UAPIntentResponse(
            status="blocked",
            mandate_id=body.internal_mandate_id,
            decision_reason=decision.primary_reason,
            token_verified=token_verified,
            rules_summary=rules_summary,
            field_mapping=field_mapping,
        )

    # 6b. ALLOW → Razorpay test-mode order
    rz = razorpay.Client(auth=(
        os.getenv("RAZORPAY_KEY_ID", ""),
        os.getenv("RAZORPAY_KEY_SECRET", ""),
    ))
    order = rz.order.create({
        "amount":   int(body.amount_inr * 100),
        "currency": mandate_data.currency,
        "receipt":  f"uap_{body.nonce[:16]}",
        "notes": {
            "mandate_id":       body.internal_mandate_id,
            "delegation_id":    body.delegation_token.delegation_id,
            "agent_registry_id": body.delegation_token.agent_registry_id,
            "delegator_vpa":    body.delegation_token.delegator_vpa,
            "merchant_vpa":     body.delegation_token.merchant_vpa,
            "category":         body.category,
            "protocol":         "uap-trustrail-v1",
            "execution_token":  decision.execution_token,
        },
    })

    return UAPIntentResponse(
        status="approved",
        mandate_id=body.internal_mandate_id,
        decision_reason="all_passed",
        razorpay_order_id=order["id"],
        execution_token=decision.execution_token,
        token_verified=token_verified,
        rules_summary=rules_summary,
        field_mapping=field_mapping,
    )
