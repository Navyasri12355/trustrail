"""
Story-12: UAP-Ready Adapter (Documented Stub)

NPCI's Unified Agent Protocol (UAP) has no public spec as of August 2026.
This adapter is designed against publicly reported UAP design intent:
  - RBI-gated delegation of payment rights to AI agents
  - Per-transaction and rolling spend limits
  - Category/merchant scope restrictions
  - Human-reviewable audit log with dispute support
  - Agent registry (agent must be pre-registered with NPCI)

Field mapping is in docs/uap-mapping.md.
This stub will be replaced with a real implementation when the UAP spec is published.

HONEST FRAMING: This is NOT a UAP compliance claim.
It is a forward-compatible design that maps cleanly onto reported UAP concepts.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import List, Optional

from backend.db.database import get_db

router = APIRouter(prefix="/adapters/uap", tags=["adapters"])


# ── UAP-shaped request schema (anticipated, not confirmed) ────────────────────

class UAPDelegationToken(BaseModel):
    """
    Anticipated UAP delegation token.
    Based on: NPCI agent registry + RBI delegation model (public reporting only).
    STATUS: ANTICIPATED — not confirmed in any public UAP spec.
    """
    delegation_id:    str   = Field(..., description="UAP delegation ID (anticipated)")
    agent_registry_id: str  = Field(..., description="NPCI agent registry ID (anticipated)")
    delegator_vpa:    str   = Field(..., description="UPI VPA of the delegating user (anticipated)")
    merchant_vpa:     str   = Field(..., description="Target merchant UPI VPA (anticipated)")
    # Spend limits — CONFIRMED from public reporting
    max_per_txn_inr:  float = Field(..., description="Per-transaction cap (CONFIRMED in reports)")
    max_rolling_inr:  float = Field(..., description="Rolling window cap (CONFIRMED in reports)")
    permitted_categories: List[str] = Field(..., description="Allowed spend categories (CONFIRMED)")
    validity_seconds: int   = Field(..., description="Token validity window (anticipated)")
    uap_signature:    str   = Field(..., description="NPCI-issued token signature (anticipated)")


class UAPPaymentIntent(BaseModel):
    """UAP payment intent submitted by an AI agent."""
    delegation_token: UAPDelegationToken
    # Map to internal mandate_id via delegation_id
    internal_mandate_id: str = Field(
        ...,
        description="TrustRail mandate_id corresponding to this UAP delegation (bridge field)"
    )
    amount_inr:  float = Field(..., gt=0)
    category:    str
    nonce:       str


# ── UAP response schema ───────────────────────────────────────────────────────

class UAPIntentResponse(BaseModel):
    uap_version:     str = "uap-ready-stub-v1"
    status:          str   # "stub_not_implemented"
    mandate_id:      str
    message:         str
    trustrail_fields: dict  # shows the internal fields this maps to


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/intent", response_model=UAPIntentResponse)
def uap_intent(body: UAPPaymentIntent, db: Session = Depends(get_db)):
    """
    Story-12: UAP-ready stub endpoint.

    This endpoint demonstrates the TrustRail→UAP field mapping.
    It does NOT execute a real payment — UAP has no public spec to implement against.
    When the spec ships, replace this stub with:
      1. NPCI token verification (uap_signature)
      2. Agent registry lookup (agent_registry_id)
      3. Delegation validation against NPCI's authorization model
      4. Map to internal MandateData and run the same guardrail engine

    See docs/uap-mapping.md for the complete field mapping table.
    """
    # Show the field translation so the stub is educational, not opaque
    trustrail_mapping = {
        "mandate_id":          body.internal_mandate_id,
        "issuer_user_id":      f"upi:{body.delegation_token.delegator_vpa}",
        "agent_id":            body.delegation_token.agent_registry_id,
        "merchant_id":         f"upi:{body.delegation_token.merchant_vpa}",
        "allowed_categories":  body.delegation_token.permitted_categories,  # CONFIRMED
        "max_per_transaction": body.delegation_token.max_per_txn_inr,       # CONFIRMED
        "max_rolling_7d":      body.delegation_token.max_rolling_inr,       # CONFIRMED
        "signature":           body.delegation_token.uap_signature,         # ANTICIPATED
        "protocol_origin":     "uap_ready",
        # Fields TrustRail adds that UAP will also need (from PRD analysis):
        "audit_trail":         "hash-chained, human-reviewable (CONFIRMED requirement)",
        "dispute_support":     "reviewer dashboard with revoke capability (CONFIRMED requirement)",
    }

    return UAPIntentResponse(
        uap_version="uap-ready-stub-v1",
        status="stub_not_implemented",
        mandate_id=body.internal_mandate_id,
        message=(
            "UAP spec not yet published (as of Aug 2026). "
            "This stub demonstrates field mapping only. "
            "See docs/uap-mapping.md for the confirmed vs anticipated breakdown."
        ),
        trustrail_fields=trustrail_mapping,
    )
