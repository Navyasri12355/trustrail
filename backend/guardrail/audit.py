"""
Story-08: Hash-chained audit log writer.

Every guardrail decision (ALLOW or BLOCK), mandate issuance, and revocation
is appended here. Each row's hash = SHA-256(prev_hash + row_data), creating
a tamper-evident chain.
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.db.models import AuditLog
from backend.guardrail.engine import GuardrailDecision, RuleResult


# ── Hash helpers ──────────────────────────────────────────────────────────────

def _row_hash(prev_hash: str, mandate_id: str, merchant_id: str, event_type: str,
              decision: Optional[str], created_at: datetime) -> str:
    """
    SHA-256( prev_hash | mandate_id | merchant_id | event_type | decision | iso_timestamp ).
    Deterministic — same inputs always produce the same hash.
    """
    data = "|".join([
        prev_hash,
        mandate_id or "",
        merchant_id or "",
        event_type,
        decision or "",
        created_at.isoformat(),
    ])
    return hashlib.sha256(data.encode()).hexdigest()


def _get_last_hash(db: Session) -> str:
    """Return the row_hash of the most recent audit entry, or '' for the genesis row."""
    last = db.query(AuditLog).order_by(AuditLog.created_at.desc()).first()
    return last.row_hash if last else ""


# ── Public writers ────────────────────────────────────────────────────────────

def log_guardrail_decision(
    db:          Session,
    mandate_id:  str,
    merchant_id: str,
    decision:    GuardrailDecision,
    amount:      float,
    category:    str,
    nonce:       str,
) -> AuditLog:
    """Append a guardrail ALLOW/BLOCK decision to the audit log."""
    prev_hash  = _get_last_hash(db)
    now        = datetime.utcnow()
    event_type = "guardrail_decision"
    dec_str    = "ALLOW" if decision.allowed else "BLOCK"

    rules_json = json.dumps([
        {"rule": r.rule, "passed": r.passed, "reason": r.reason}
        for r in decision.rules
    ])

    rh = _row_hash(prev_hash, mandate_id, merchant_id, event_type, dec_str, now)

    entry = AuditLog(
        id=str(uuid.uuid4()),
        mandate_id=mandate_id,
        merchant_id=merchant_id,
        event_type=event_type,
        decision=dec_str,
        rules_checked=rules_json,
        reason=decision.primary_reason,
        amount=amount,
        category=category,
        nonce=nonce,
        created_at=now,
        prev_hash=prev_hash,
        row_hash=rh,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def log_mandate_event(
    db:         Session,
    mandate_id: str,
    merchant_id: str,
    event_type: str,   # "mandate_issued" | "mandate_revoked"
) -> AuditLog:
    """Append a mandate lifecycle event (issued / revoked) to the audit log."""
    prev_hash = _get_last_hash(db)
    now       = datetime.utcnow()

    rh = _row_hash(prev_hash, mandate_id, merchant_id, event_type, None, now)

    entry = AuditLog(
        id=str(uuid.uuid4()),
        mandate_id=mandate_id,
        merchant_id=merchant_id,
        event_type=event_type,
        decision=None,
        rules_checked=None,
        reason=None,
        amount=None,
        category=None,
        nonce=None,
        created_at=now,
        prev_hash=prev_hash,
        row_hash=rh,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
