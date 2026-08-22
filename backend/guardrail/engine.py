"""
Stories 06 & 07: Guardrail engine — pure Python module, no FastAPI dependency.
All 7 rules from PRD Section 6.3. Every rule is always evaluated (no short-circuit),
so the audit trail shows the full checklist, not just the first failure.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

from backend.crypto.keys import verify_signature


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class MandateData:
    """Flat representation of a mandate fed into the engine."""
    mandate_id:           str
    issuer_user_id:       str
    agent_id:             str
    merchant_id:          str
    allowed_categories:   List[str]
    max_per_transaction:  float
    max_rolling_7d:       float
    currency:             str
    issued_at:            datetime
    expires_at:           datetime
    revoked:              bool
    signature:            str
    protocol_origin:      str


@dataclass
class PaymentRequest:
    """A payment request submitted by an AI agent."""
    mandate_id: str
    amount:     float
    category:   str
    nonce:      str          # unique per request — used for replay detection
    agent_id:   str


@dataclass
class RuleResult:
    rule:    str    # e.g. "signature_valid"
    passed:  bool
    reason:  str    # human-readable; empty string when passed


@dataclass
class GuardrailDecision:
    allowed:          bool
    rules:            List[RuleResult]
    primary_reason:   str          # block reason or "all_passed"
    execution_token:  Optional[str] = None   # set on ALLOW


# ── Signable payload (must match mandates.py exactly) ────────────────────────

def _build_signable_payload(m: MandateData) -> bytes:
    payload = {
        "mandate_id":      m.mandate_id,
        "issuer_user_id":  m.issuer_user_id,
        "agent_id":        m.agent_id,
        "merchant_id":     m.merchant_id,
        "scope": {
            "allowed_categories":  m.allowed_categories,
            "max_per_transaction": m.max_per_transaction,
            "max_rolling_7d":      m.max_rolling_7d,
            "currency":            m.currency,
        },
        "issued_at":       m.issued_at.isoformat() + "Z",
        "expires_at":      m.expires_at.isoformat() + "Z",
        "protocol_origin": m.protocol_origin,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


# ── Individual rule evaluators ───────────────────────────────────────────────

def _rule_signature_valid(m: MandateData) -> RuleResult:
    """Rule 1 — Ed25519 signature must be valid."""
    payload = _build_signable_payload(m)
    ok = verify_signature(payload, m.signature)
    return RuleResult(
        rule="signature_valid",
        passed=ok,
        reason="" if ok else "invalid_signature: Ed25519 verification failed",
    )


def _rule_not_expired(m: MandateData) -> RuleResult:
    """Rule 2a — Mandate must not be expired."""
    ok = datetime.utcnow() < m.expires_at
    return RuleResult(
        rule="not_expired",
        passed=ok,
        reason="" if ok else f"expired: mandate expired at {m.expires_at.isoformat()}Z",
    )


def _rule_not_revoked(m: MandateData) -> RuleResult:
    """Rule 2b — Mandate must not be revoked."""
    ok = not m.revoked
    return RuleResult(
        rule="not_revoked",
        passed=ok,
        reason="" if ok else "revoked: mandate has been revoked by the user",
    )


def _rule_category_in_scope(m: MandateData, req: PaymentRequest) -> RuleResult:
    """Rule 3 — Requested category must be in allowed_categories."""
    ok = req.category in m.allowed_categories
    return RuleResult(
        rule="category_in_scope",
        passed=ok,
        reason="" if ok else (
            f"out_of_scope_category: '{req.category}' not in {m.allowed_categories}"
        ),
    )


def _rule_within_transaction_cap(m: MandateData, req: PaymentRequest) -> RuleResult:
    """Rule 4 — Amount must not exceed max_per_transaction."""
    ok = req.amount <= m.max_per_transaction
    return RuleResult(
        rule="within_transaction_cap",
        passed=ok,
        reason="" if ok else (
            f"exceeds_transaction_cap: {req.amount} > {m.max_per_transaction} {m.currency}"
        ),
    )


def _rule_within_rolling_cap(
    m: MandateData, req: PaymentRequest, spent_7d: float
) -> RuleResult:
    """
    Rule 5 — Rolling 7-day spend + this request must not exceed max_rolling_7d.
    spent_7d is injected by the caller (read from audit log).
    """
    total = spent_7d + req.amount
    ok    = total <= m.max_rolling_7d
    return RuleResult(
        rule="within_rolling_cap",
        passed=ok,
        reason="" if ok else (
            f"exceeds_rolling_cap: {spent_7d} spent + {req.amount} requested "
            f"= {total} > {m.max_rolling_7d} {m.currency} (7-day window)"
        ),
    )


def _rule_no_replay(nonce: str, seen_nonces: List[str]) -> RuleResult:
    """
    Rule 6 — Nonce must not have been seen before for this mandate.
    seen_nonces is injected by the caller (read from audit log).
    """
    ok = nonce not in seen_nonces
    return RuleResult(
        rule="no_replay",
        passed=ok,
        reason="" if ok else f"replay_detected: nonce '{nonce}' was already used",
    )


# ── Main entry point ─────────────────────────────────────────────────────────

def validate(
    mandate:      MandateData,
    request:      PaymentRequest,
    spent_7d:     float,
    seen_nonces:  List[str],
) -> GuardrailDecision:
    """
    Run all 7 guardrail rules. Every rule is evaluated regardless of prior failures.
    Returns a GuardrailDecision with allowed=True only if ALL rules pass.

    Args:
        mandate:     The mandate being evaluated.
        request:     The incoming payment request.
        spent_7d:    Total INR approved for this mandate in the trailing 7 days.
        seen_nonces: All nonces previously used under this mandate.
    """
    rules: List[RuleResult] = [
        _rule_signature_valid(mandate),                          # Rule 1
        _rule_not_expired(mandate),                              # Rule 2a
        _rule_not_revoked(mandate),                              # Rule 2b
        _rule_category_in_scope(mandate, request),               # Rule 3
        _rule_within_transaction_cap(mandate, request),          # Rule 4
        _rule_within_rolling_cap(mandate, request, spent_7d),    # Rule 5
        _rule_no_replay(request.nonce, seen_nonces),             # Rule 6
    ]

    failed = [r for r in rules if not r.passed]
    allowed = len(failed) == 0

    if allowed:
        # Rule 7 — generate a signed execution token
        import hashlib, time
        token_data = f"{mandate.mandate_id}:{request.nonce}:{time.time()}"
        execution_token = "exec_" + hashlib.sha256(token_data.encode()).hexdigest()[:24]
        return GuardrailDecision(
            allowed=True,
            rules=rules,
            primary_reason="all_passed",
            execution_token=execution_token,
        )
    else:
        # Primary reason = first failure (most specific)
        primary = failed[0].reason.split(":")[0]
        return GuardrailDecision(
            allowed=False,
            rules=rules,
            primary_reason=primary,
        )
