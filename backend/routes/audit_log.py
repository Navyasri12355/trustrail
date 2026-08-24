"""
Story-08 (continued): GET /audit-log endpoint.
Returns the full hash-chained audit trail in chronological order.
Requires authentication for dashboard access.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import AuditLog
from backend.routes.auth import get_current_user

router = APIRouter(tags=["audit"])


class AuditEntryOut(BaseModel):
    id:           str
    mandate_id:   Optional[str]
    merchant_id:  Optional[str]
    event_type:   str
    decision:     Optional[str]
    rules_checked: Optional[str]
    reason:       Optional[str]
    amount:       Optional[float]
    category:     Optional[str]
    nonce:        Optional[str]
    created_at:   str
    prev_hash:    str
    row_hash:     str


@router.get("/audit-log", response_model=List[AuditEntryOut])
def get_audit_log(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Return the full audit trail in chronological order.
    Requires authentication (admin access only).
    """
    rows = db.query(AuditLog).order_by(AuditLog.created_at.asc()).all()
    return [
        AuditEntryOut(
            id=r.id,
            mandate_id=r.mandate_id,
            merchant_id=r.merchant_id,
            event_type=r.event_type,
            decision=r.decision,
            rules_checked=r.rules_checked,
            reason=r.reason,
            amount=r.amount,
            category=r.category,
            nonce=r.nonce,
            created_at=r.created_at.isoformat() + "Z",
            prev_hash=r.prev_hash,
            row_hash=r.row_hash,
        )
        for r in rows
    ]
