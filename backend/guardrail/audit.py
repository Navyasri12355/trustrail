"""
Story-08: Hash-chained audit log writer.

Every guardrail decision (ALLOW or BLOCK), mandate issuance, and revocation
is appended here. Each row's hash = SHA-256(prev_hash + row_data), creating
a tamper-evident chain.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.db.models import AuditLog
from backend.guardrail.engine import GuardrailDecision

# ── Hash helpers ──────────────────────────────────────────────────────────────


def _row_hash(
    prev_hash: str,
    mandate_id: str,
    merchant_id: str,
    event_type: str,
    decision: str | None,
    created_at: datetime,
) -> str:
    """
    SHA-256( prev_hash | mandate_id | merchant_id | event_type | decision | iso_timestamp ).
    Deterministic — same inputs always produce the same hash.
    """
    data = "|".join(
        [
            prev_hash,
            mandate_id or "",
            merchant_id or "",
            event_type,
            decision or "",
            created_at.isoformat(),
        ]
    )
    return hashlib.sha256(data.encode()).hexdigest()


def _get_last_hash(db: Session, merchant_id: str | None = None) -> str:
    """
    Return the row_hash of the most recent audit entry, or '' for the genesis row.

    If merchant_id is provided, returns the last hash for that merchant only.
    If merchant_id is None, returns the global last hash (for hash chain continuity).
    created_at + id is the tie-breaker so verify_chain() walks the same order.
    """
    query = db.query(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    if merchant_id:
        query = query.filter(AuditLog.merchant_id == merchant_id)
    last = query.first()
    return last.row_hash if last else ""


# ── Public writers ────────────────────────────────────────────────────────────


def log_guardrail_decision(
    db: Session,
    mandate_id: str,
    merchant_id: str,
    decision: GuardrailDecision,
    amount: float,
    category: str,
    nonce: str,
) -> AuditLog:
    """Append a guardrail ALLOW/BLOCK decision to the audit log."""
    prev_hash = _get_last_hash(db)  # Global hash chain for tamper evidence
    now = datetime.now(tz=timezone.utc)
    event_type = "guardrail_decision"
    dec_str = "ALLOW" if decision.allowed else "BLOCK"

    rules_json = json.dumps(
        [
            {"rule": r.rule, "passed": r.passed, "reason": r.reason}
            for r in decision.rules
        ]
    )

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
    db: Session,
    mandate_id: str,
    merchant_id: str,
    event_type: str,  # "mandate_issued" | "mandate_revoked"
) -> AuditLog:
    """Append a mandate lifecycle event (issued / revoked) to the audit log."""
    prev_hash = _get_last_hash(db)  # Global hash chain for tamper evidence
    now = datetime.now(tz=timezone.utc)

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


def verify_chain(db: Session) -> dict:
    """
    Recompute every row hash against prev_hash and detect breaks.

    The chain is global (same as _get_last_hash without a merchant filter),
    because a merchant-scoped walk would false-fail when prev_hash points
    at another tenant's row.
    """
    rows = (
        db.query(AuditLog).order_by(AuditLog.created_at.asc(), AuditLog.id.asc()).all()
    )
    expected_prev = ""
    for index, row in enumerate(rows):
        if row.prev_hash != expected_prev:
            return {
                "intact": False,
                "rows_checked": len(rows),
                "break_at": row.id,
                "detail": (
                    f"prev_hash mismatch at index {index}: "
                    f"expected '{expected_prev or '(genesis)'}'"
                ),
            }
        expected_hash = _row_hash(
            row.prev_hash,
            row.mandate_id,
            row.merchant_id,
            row.event_type,
            row.decision,
            row.created_at,
        )
        if row.row_hash != expected_hash:
            return {
                "intact": False,
                "rows_checked": len(rows),
                "break_at": row.id,
                "detail": f"row_hash mismatch at index {index}",
            }
        expected_prev = row.row_hash

    return {
        "intact": True,
        "rows_checked": len(rows),
        "break_at": None,
        "detail": "chain intact" if rows else "empty chain",
    }
