"""
Pytest configuration and fixtures for TrustRail backend tests.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Set test environment variables before importing backend modules
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["ED25519_PRIVATE_KEY_HEX"] = "0000000000000000000000000000000000000000000000000000000000000001"
os.environ["ED25519_PUBLIC_KEY_HEX"] = "4cb5abf6ad79fbf5abbccafcc269d85cd2651ed4b885b5869f241aedf0a5ba29"
os.environ["JWT_SECRET_KEY"] = "test_secret_key_for_ci_min_32_chars_long"
os.environ["DASHBOARD_ADMIN_USERNAME"] = "admin"
os.environ["DASHBOARD_ADMIN_PASSWORD"] = "admin123"

from backend.db import models
from backend.db.database import get_db


# Test database setup
TEST_DATABASE_URL = "sqlite:///./test.db"
test_engine = create_engine(
    TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    models.Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        # Clean up - drop all tables after test
        models.Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def sample_mandate_data():
    """Sample mandate data for testing."""
    from backend.guardrail.engine import MandateData
    from backend.crypto.keys import sign_payload
    import json

    # Create a valid signature for the mandate data
    mandate_payload = {
        "mandate_id": "test_mandate_001",
        "issuer_user_id": "user_001",
        "agent_id": "agent_001",
        "merchant_id": "merchant_001",
        "allowed_categories": ["groceries", "household"],
        "max_per_transaction": 500.0,
        "max_rolling_7d": 2000.0,
        "currency": "INR",
    }
    payload_bytes = json.dumps(mandate_payload, sort_keys=True, separators=(",", ":")).encode()
    signature = sign_payload(payload_bytes)

    return MandateData(
        mandate_id="test_mandate_001",
        issuer_user_id="user_001",
        agent_id="agent_001",
        merchant_id="merchant_001",
        allowed_categories=["groceries", "household"],
        max_per_transaction=500.0,
        max_rolling_7d=2000.0,
        currency="INR",
        issued_at=datetime.now(tz=timezone.utc),
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
        revoked=False,
        signature=signature,
        protocol_origin="internal",
    )


@pytest.fixture(scope="function")
def sample_payment_request():
    """Sample payment request for testing."""
    from backend.guardrail.engine import PaymentRequest

    return PaymentRequest(
        mandate_id="test_mandate_001",
        amount=299.0,
        category="groceries",
        nonce="test_nonce_001",
        agent_id="agent_001",
    )
