"""
Tests for database models (db/models.py).
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.db.models import AuditLog, Mandate, Merchant


class TestMerchantModel:
    """Test Merchant model."""

    def test_create_merchant(self, db_session):
        """Should successfully create a merchant."""
        merchant = Merchant(
            merchant_id="mrc_test_001",
            merchant_name="Test Merchant",
            razorpay_key_id="rzp_test_key",
            razorpay_key_secret="rzp_test_secret",
            currency="INR",
            active=True,
        )
        db_session.add(merchant)
        db_session.commit()
        db_session.refresh(merchant)

        assert merchant.merchant_id == "mrc_test_001"
        assert merchant.merchant_name == "Test Merchant"
        assert merchant.active is True
        assert merchant.created_at is not None

    def test_merchant_defaults(self, db_session):
        """Should apply default values correctly."""
        merchant = Merchant(
            merchant_id="mrc_test_002",
            merchant_name="Test Merchant 2",
            razorpay_key_id="rzp_test_key_2",
            razorpay_key_secret="rzp_test_secret_2",
        )
        db_session.add(merchant)
        db_session.commit()
        db_session.refresh(merchant)

        assert merchant.currency == "INR"
        assert merchant.active is True


class TestMandateModel:
    """Test Mandate model."""

    def test_create_mandate(self, db_session):
        """Should successfully create a mandate."""
        # First create a merchant
        merchant = Merchant(
            merchant_id="mrc_test_003",
            merchant_name="Test Merchant 3",
            razorpay_key_id="rzp_test_key_3",
            razorpay_key_secret="rzp_test_secret_3",
        )
        db_session.add(merchant)
        db_session.commit()

        # Now create mandate
        mandate = Mandate(
            mandate_id="mnd_test_001",
            issuer_user_id="user_001",
            agent_id="agent_001",
            merchant_id="mrc_test_003",
            allowed_categories='["groceries", "household"]',
            max_per_transaction=500.0,
            max_rolling_7d=2000.0,
            currency="INR",
            expires_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
            signature="ed25519:test_signature",
            protocol_origin="internal",
        )
        db_session.add(mandate)
        db_session.commit()
        db_session.refresh(mandate)

        assert mandate.mandate_id == "mnd_test_001"
        assert mandate.revoked is False
        assert mandate.issued_at is not None

    def test_mandate_merchant_relationship(self, db_session):
        """Should correctly link mandate to merchant."""
        merchant = Merchant(
            merchant_id="mrc_test_004",
            merchant_name="Test Merchant 4",
            razorpay_key_id="rzp_test_key_4",
            razorpay_key_secret="rzp_test_secret_4",
        )
        db_session.add(merchant)
        db_session.commit()

        mandate = Mandate(
            mandate_id="mnd_test_002",
            issuer_user_id="user_002",
            agent_id="agent_002",
            merchant_id="mrc_test_004",
            allowed_categories='["groceries"]',
            max_per_transaction=300.0,
            max_rolling_7d=1000.0,
            currency="INR",
            expires_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
            signature="ed25519:test_signature",
            protocol_origin="internal",
        )
        db_session.add(mandate)
        db_session.commit()

        # Query mandate and check relationship
        retrieved_mandate = (
            db_session.query(Mandate)
            .filter(Mandate.mandate_id == "mnd_test_002")
            .first()
        )
        assert retrieved_mandate.merchant_id == "mrc_test_004"


class TestAuditLogModel:
    """Test AuditLog model."""

    def test_create_audit_log(self, db_session):
        """Should successfully create an audit log entry."""
        # Create merchant first
        merchant = Merchant(
            merchant_id="mrc_test_005",
            merchant_name="Test Merchant 5",
            razorpay_key_id="rzp_test_key_5",
            razorpay_key_secret="rzp_test_secret_5",
        )
        db_session.add(merchant)
        db_session.commit()

        # Create mandate
        mandate = Mandate(
            mandate_id="mnd_test_003",
            issuer_user_id="user_003",
            agent_id="agent_003",
            merchant_id="mrc_test_005",
            allowed_categories='["groceries"]',
            max_per_transaction=300.0,
            max_rolling_7d=1000.0,
            currency="INR",
            expires_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
            signature="ed25519:test_signature",
            protocol_origin="internal",
        )
        db_session.add(mandate)
        db_session.commit()

        # Create audit log
        audit_log = AuditLog(
            mandate_id="mnd_test_003",
            merchant_id="mrc_test_005",
            event_type="guardrail_decision",
            decision="ALLOW",
            rules_checked='[{"rule": "signature_valid", "passed": true}]',
            reason="all_passed",
            amount=299.0,
            category="groceries",
            nonce="test_nonce_001",
            prev_hash="",
            row_hash="test_hash",
        )
        db_session.add(audit_log)
        db_session.commit()
        db_session.refresh(audit_log)

        assert audit_log.id is not None
        assert audit_log.decision == "ALLOW"
        assert audit_log.amount == 299.0
        assert audit_log.created_at is not None

    def test_audit_log_defaults(self, db_session):
        """Should apply default values correctly."""
        merchant = Merchant(
            merchant_id="mrc_test_006",
            merchant_name="Test Merchant 6",
            razorpay_key_id="rzp_test_key_6",
            razorpay_key_secret="rzp_test_secret_6",
        )
        db_session.add(merchant)
        db_session.commit()

        audit_log = AuditLog(
            merchant_id="mrc_test_006",
            event_type="mandate_issued",
            prev_hash="",
            row_hash="test_hash_2",
        )
        db_session.add(audit_log)
        db_session.commit()
        db_session.refresh(audit_log)

        assert audit_log.decision is None
        assert audit_log.amount is None
        assert audit_log.nonce is None
