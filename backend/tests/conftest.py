"""
Pytest configuration and shared fixtures for TrustRail backend tests.

Key design decisions:
- Uses SQLite in-memory DB per test function → zero cross-test pollution.
- TestClient runs the full ASGI app in-process → no server needed.
- Rate limiter is overridden with a no-op → no 429s in tests.
- Demo merchant (mrc_demo_001) is seeded per test that needs it.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Set env vars BEFORE any backend import ────────────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault(
    "ED25519_PRIVATE_KEY_HEX",
    "0000000000000000000000000000000000000000000000000000000000000001",
)
os.environ.setdefault(
    "ED25519_PUBLIC_KEY_HEX",
    "4cb5abf6ad79fbf5abbccafcc269d85cd2651ed4b885b5869f241aedf0a5ba29",
)
os.environ.setdefault("JWT_SECRET_KEY", "test_secret_key_for_ci_min_32_chars_long")
os.environ.setdefault("DASHBOARD_ADMIN_USERNAME", "admin")
os.environ.setdefault("DASHBOARD_ADMIN_PASSWORD", "admin123")
os.environ.setdefault("RAZORPAY_KEY_ID", "rzp_test_ci_key")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "rzp_test_ci_secret")
os.environ.setdefault("TRUSTRAIL_MERCHANT_ID", "mrc_demo_001")
os.environ.setdefault("TRUSTRAIL_MERCHANT_NAME", "Demo Merchant")

from backend.db import models
from backend.db.database import get_db

# ── In-memory SQLite engine (StaticPool = single connection per test) ─────────
_TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_TEST_ENGINE)

DEMO_MERCHANT_ID = "mrc_demo_001"


def _make_demo_merchant():
    from backend.db.models import Merchant

    return Merchant(
        merchant_id=DEMO_MERCHANT_ID,
        merchant_name="Demo Merchant",
        razorpay_key_id="rzp_test_ci_key",
        razorpay_key_secret="rzp_test_ci_secret",
        currency="INR",
        active=True,
        created_at=datetime.now(tz=timezone.utc),
    )


# ── Per-test isolated DB session ──────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_session():
    """Fresh schema + session for each test; torn down afterwards."""
    models.Base.metadata.create_all(bind=_TEST_ENGINE)
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()
        models.Base.metadata.drop_all(bind=_TEST_ENGINE)


# ── TestClient wired to the in-memory DB ─────────────────────────────────────


@pytest.fixture(scope="function")
def client(db_session):
    """
    FastAPI TestClient backed by an isolated in-memory SQLite DB.

    - Overrides get_db to use the test session.
    - Disables slowapi rate limiter (avoids 429 in unit tests).
    - Pre-seeds the demo merchant so all tenant-gated routes work.
    """
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    # Seed demo merchant
    db_session.add(_make_demo_merchant())
    db_session.commit()

    from backend.main import app

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    # Disable rate limiter
    _noop_limiter = Limiter(key_func=get_remote_address, enabled=False)
    original_limiter = app.state.limiter
    app.state.limiter = _noop_limiter

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.pop(get_db, None)
    app.state.limiter = original_limiter


# ── Convenience fixture for the demo merchant header ─────────────────────────


@pytest.fixture(scope="function")
def demo_headers():
    """X-Merchant-ID header pointing at the seeded demo merchant."""
    return {"X-Merchant-ID": DEMO_MERCHANT_ID}


# ── Reusable guardrail-engine fixtures ───────────────────────────────────────


@pytest.fixture(scope="function")
def sample_mandate_data():
    """Valid MandateData with a real Ed25519 signature."""
    import json

    from backend.crypto.keys import sign_payload
    from backend.guardrail.engine import MandateData

    now = datetime.now(tz=timezone.utc)
    mandate_payload = {
        "mandate_id": "test_mandate_001",
        "issuer_user_id": "user_001",
        "agent_id": "agent_001",
        "merchant_id": "merchant_001",
        "scope": {
            "allowed_categories": ["groceries", "household"],
            "max_per_transaction": 500.0,
            "max_rolling_7d": 2000.0,
            "currency": "INR",
        },
        "issued_at": now.isoformat() + "Z",
        "expires_at": (now + timedelta(days=30)).isoformat() + "Z",
        "protocol_origin": "internal",
    }
    payload_bytes = json.dumps(
        mandate_payload, sort_keys=True, separators=(",", ":")
    ).encode()
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
        issued_at=now,
        expires_at=now + timedelta(days=30),
        revoked=False,
        signature=signature,
        protocol_origin="internal",
    )


@pytest.fixture(scope="function")
def sample_payment_request():
    """Sample PaymentRequest for guardrail engine tests."""
    from backend.guardrail.engine import PaymentRequest

    return PaymentRequest(
        mandate_id="test_mandate_001",
        amount=299.0,
        category="groceries",
        nonce="test_nonce_001",
        agent_id="agent_001",
    )
