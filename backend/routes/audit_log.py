"""
Story-08 (continued): GET /audit-log endpoint.
Returns the full hash-chained audit trail in chronological order.
Requires authentication for dashboard access.
Enforces tenant isolation - returns only audit logs for the specified merchant.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import AuditLog, Merchant
from backend.dependencies.tenant import get_merchant_from_header
from backend.guardrail import audit as audit_writer
from backend.routes.auth import get_current_user

router = APIRouter(tags=["audit"])


class AuditEntryOut(BaseModel):
    id: str
    mandate_id: str | None
    merchant_id: str | None
    event_type: str
    decision: str | None
    rules_checked: str | None
    reason: str | None
    amount: float | None
    category: str | None
    nonce: str | None
    created_at: str
    prev_hash: str
    row_hash: str


class ChainVerifyOut(BaseModel):
    intact: bool
    rows_checked: int
    break_at: str | None
    detail: str


@router.get("/audit-log", response_model=list[AuditEntryOut])
def get_audit_log(
    merchant: Merchant = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """
    Return the audit trail for the specified merchant in chronological order.
    Requires X-Merchant-ID header and a dashboard JWT.
    """
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.merchant_id == merchant.merchant_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )
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


@router.get("/audit-log/verify", response_model=ChainVerifyOut)
def verify_audit_chain(
    merchant: Merchant = Depends(get_merchant_from_header),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """
    Recompute the global SHA-256 audit chain.
    Tenant header is required so only a logged-in reviewer can run this;
    verification itself walks every row (chain is process-global).
    """
    # merchant is authenticated/isolated even though the chain is global
    _ = merchant
    result = audit_writer.verify_chain(db)
    return ChainVerifyOut(**result)
