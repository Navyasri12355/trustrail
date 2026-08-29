"""
Story-03: SQLAlchemy models for mandates and audit_log tables.
Schema matches PRD Section 6.2.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Merchant(Base):
    """
    Multi-tenant merchant configuration.
    Each merchant has their own mandates, audit logs, and Razorpay credentials.
    """

    __tablename__ = "merchants"

    merchant_id = Column(String, primary_key=True, index=True)  # mrc_<uuid>
    merchant_name = Column(String, nullable=False)
    razorpay_key_id = Column(String, nullable=False)
    razorpay_key_secret = Column(String, nullable=False)
    currency = Column(String, default="INR")
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(tz=timezone.utc), nullable=False
    )


class Mandate(Base):
    """
    Signed, scoped, expiring permission object.
    PRD Section 6.2 schema.
    """

    __tablename__ = "mandates"

    mandate_id = Column(String, primary_key=True, index=True)  # mnd_<uuid>
    issuer_user_id = Column(String, nullable=False)
    agent_id = Column(String, nullable=False)
    merchant_id = Column(
        String, ForeignKey("merchants.merchant_id"), nullable=False, index=True
    )

    # Scope stored as individual columns for easy querying
    allowed_categories = Column(
        Text, nullable=False
    )  # JSON array string, e.g. '["groceries","household"]'
    max_per_transaction = Column(Float, nullable=False)  # INR
    max_rolling_7d = Column(Float, nullable=False)  # INR
    currency = Column(String, default="INR")

    issued_at = Column(
        DateTime, default=lambda: datetime.now(tz=timezone.utc), nullable=False
    )
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)

    signature = Column(Text, nullable=False)  # "ed25519:<hex>"
    protocol_origin = Column(
        String, default="internal"
    )  # "ap2" | "ucp" | "uap_ready" | "internal"


class AuditLog(Base):
    """
    Append-only, hash-chained log of every guardrail decision.
    PRD Section 3 — immutable audit trail requirement.
    """

    __tablename__ = "audit_log"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    mandate_id = Column(String, ForeignKey("mandates.mandate_id"), nullable=True)
    merchant_id = Column(
        String, ForeignKey("merchants.merchant_id"), nullable=False, index=True
    )
    event_type = Column(
        String, nullable=False
    )  # "guardrail_decision" | "mandate_issued" | "mandate_revoked"
    decision = Column(String, nullable=True)  # "ALLOW" | "BLOCK"
    rules_checked = Column(Text, nullable=True)  # JSON list of RuleResult dicts
    reason = Column(String, nullable=True)  # primary block reason or "all_passed"
    amount = Column(Float, nullable=True)  # requested amount
    category = Column(String, nullable=True)  # requested category
    nonce = Column(String, nullable=True)  # request nonce (for replay detection)
    created_at = Column(
        DateTime, default=lambda: datetime.now(tz=timezone.utc), nullable=False
    )
    prev_hash = Column(String, nullable=False, default="")  # SHA-256 of previous row
    row_hash = Column(String, nullable=False, default="")  # SHA-256 of this row's data
