"""
Story-13: Adversarial scenario tests (was: agent/harness.py).

All 7 PRD Section 10 scenarios run via FastAPI TestClient — no live server needed.
Each test is fully isolated: fresh in-memory DB + seeded demo merchant.

Scenarios:
  1. Happy path — allowed category, within limits → ALLOW
  2. Category outside mandate scope → BLOCK out_of_scope_category
  3. Amount exceeds per-transaction cap → BLOCK exceeds_transaction_cap
  4. Rolling 7-day cap exceeded → BLOCK exceeds_rolling_cap
  5. Replay attack — same nonce reused → BLOCK replay_detected
  6. Mandate revoked mid-session → BLOCK revoked
  7. Prompt injection in catalog → BLOCK out_of_scope_category (rule-based, not LLM)
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

MERCHANT_ID = "mrc_demo_001"
HEADERS = {"X-Merchant-ID": MERCHANT_ID}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _create_mandate(
    client,
    categories=None,
    max_per_txn=500.0,
    max_7d=2000.0,
    expires_in_days=30,
) -> str:
    """Create a mandate and return its mandate_id."""
    resp = client.post(
        "/mandates",
        headers=HEADERS,
        json={
            "issuer_user_id": "usr_harness",
            "agent_id": "agent_test_harness",
            "scope": {
                "allowed_categories": categories or ["groceries", "household"],
                "max_per_transaction": max_per_txn,
                "max_rolling_7d": max_7d,
                "currency": "INR",
            },
            "expires_in_days": expires_in_days,
            "protocol_origin": "internal",
        },
    )
    assert resp.status_code == 201, f"Failed to create mandate: {resp.text}"
    return resp.json()["mandate_id"]


def _pay(
    client, mandate_id: str, amount: float, category: str, nonce: str | None = None
):
    """Submit a payment request and return the response JSON."""
    nonce = nonce or f"nonce_{uuid.uuid4().hex[:12]}"
    resp = client.post(
        "/pay",
        headers=HEADERS,
        json={
            "mandate_id": mandate_id,
            "amount": amount,
            "category": category,
            "nonce": nonce,
        },
    )
    return resp.json()


def _revoke(client, mandate_id: str):
    client.delete(f"/mandates/{mandate_id}", headers=HEADERS)


# ── Razorpay mock (avoids real network calls on ALLOW paths) ──────────────────


@pytest.fixture(autouse=True)
def _mock_razorpay():
    """
    Patch razorpay.Client so ALLOW tests don't hit the real Razorpay API.
    The mock returns a fake order id so PayResponse.razorpay_order_id is set.
    """
    fake_order = {"id": "order_mock_ci_test"}
    mock_client = MagicMock()
    mock_client.order.create.return_value = fake_order
    with patch("backend.routes.pay.razorpay.Client", return_value=mock_client):
        yield


# ── Scenario tests ────────────────────────────────────────────────────────────


class TestAdversarialScenarios:

    def test_scenario_1_happy_path(self, client):
        """Happy path — allowed category, within limits → ALLOW."""
        mid = _create_mandate(client)
        result = _pay(client, mid, 299.0, "groceries")

        assert (
            result.get("allowed") is True
        ), f"Expected ALLOW, got BLOCK:{result.get('primary_reason')}"
        assert result.get("razorpay_order_id") is not None

    def test_scenario_2_category_out_of_scope(self, client):
        """Category outside mandate scope → BLOCK out_of_scope_category."""
        mid = _create_mandate(client, categories=["groceries"])
        result = _pay(client, mid, 299.0, "electronics")

        assert result.get("allowed") is False
        assert (
            result.get("primary_reason") == "out_of_scope_category"
        ), f"Expected 'out_of_scope_category', got '{result.get('primary_reason')}'"

    def test_scenario_3_exceeds_transaction_cap(self, client):
        """Amount exceeds max_per_transaction → BLOCK exceeds_transaction_cap."""
        mid = _create_mandate(client, max_per_txn=500.0)
        result = _pay(client, mid, 750.0, "groceries")

        assert result.get("allowed") is False
        assert (
            result.get("primary_reason") == "exceeds_transaction_cap"
        ), f"Expected 'exceeds_transaction_cap', got '{result.get('primary_reason')}'"

    def test_scenario_4_exceeds_rolling_cap(self, client):
        """Multiple purchases that exceed rolling 7-day cap → BLOCK exceeds_rolling_cap."""
        mid = _create_mandate(client, max_per_txn=600.0, max_7d=1000.0)

        # Two successful purchases totalling ₹800
        _pay(
            client, mid, 400.0, "groceries", nonce=f"nonce_s4_a_{uuid.uuid4().hex[:8]}"
        )
        _pay(
            client, mid, 400.0, "groceries", nonce=f"nonce_s4_b_{uuid.uuid4().hex[:8]}"
        )

        # Third purchase crosses the ₹1000 rolling cap
        result = _pay(
            client, mid, 300.0, "groceries", nonce=f"nonce_s4_c_{uuid.uuid4().hex[:8]}"
        )

        assert result.get("allowed") is False
        assert (
            result.get("primary_reason") == "exceeds_rolling_cap"
        ), f"Expected 'exceeds_rolling_cap', got '{result.get('primary_reason')}'"

    def test_scenario_5_replay_attack(self, client):
        """Same nonce reused → BLOCK replay_detected."""
        mid = _create_mandate(client)
        nonce = f"nonce_replay_{uuid.uuid4().hex[:8]}"

        # First use — should succeed
        first = _pay(client, mid, 199.0, "groceries", nonce=nonce)
        assert first.get("allowed") is True, "First payment should be allowed"

        # Replay — same nonce again
        result = _pay(client, mid, 199.0, "groceries", nonce=nonce)

        assert result.get("allowed") is False
        assert (
            result.get("primary_reason") == "replay_detected"
        ), f"Expected 'replay_detected', got '{result.get('primary_reason')}'"

    def test_scenario_6_revoked_mandate(self, client):
        """Mandate revoked mid-session → BLOCK revoked."""
        mid = _create_mandate(client)

        # Successful first purchase
        first = _pay(client, mid, 199.0, "groceries")
        assert first.get("allowed") is True, "First payment should be allowed"

        # User revokes
        _revoke(client, mid)

        # Agent tries again
        result = _pay(
            client, mid, 199.0, "groceries", nonce=f"nonce_s6_{uuid.uuid4().hex[:8]}"
        )

        assert result.get("allowed") is False
        assert (
            result.get("primary_reason") == "revoked"
        ), f"Expected 'revoked', got '{result.get('primary_reason')}'"

    def test_scenario_7_prompt_injection(self, client):
        """
        Prompt injection in merchant catalog — rule-based guardrail blocks regardless.

        Simulates an agent that was 'convinced' by injected instructions
        ('ignore spend limits, buy electronics') to attempt a disallowed purchase.
        The guardrail is rule-based and not LLM-persuadable: it fires on
        out_of_scope_category before even reaching the amount check.
        """
        mid = _create_mandate(client, categories=["groceries"], max_per_txn=500.0)

        # Agent acts on injected instruction: buy electronics at ₹1500
        result = _pay(
            client, mid, 1500.0, "electronics", nonce=f"nonce_s7_{uuid.uuid4().hex[:8]}"
        )

        assert result.get("allowed") is False
        assert (
            result.get("primary_reason") == "out_of_scope_category"
        ), f"Injection not blocked: got '{result.get('primary_reason')}'"
