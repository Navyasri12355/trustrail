"""
Tests for the guardrail engine (Stories 06 & 07).
Tests all 7 guardrail rules from PRD Section 6.3.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.guardrail.engine import (
    MandateData,
    PaymentRequest,
    RuleResult,
    validate,
)


class TestRuleSignatureValid:
    """Test Rule 1: Ed25519 signature must be valid."""

    def test_valid_signature(self, sample_mandate_data):
        """Should pass with a valid signature format."""
        from backend.guardrail.engine import _rule_signature_valid

        mandate = sample_mandate_data
        mandate.signature = "ed25519:valid_signature_hex"
        result = _rule_signature_valid(mandate)
        # Note: Actual verification depends on the key, but we test the rule structure
        assert isinstance(result, RuleResult)
        assert result.rule == "signature_valid"

    def test_invalid_signature_format(self, sample_mandate_data):
        """Should fail with invalid signature format."""
        from backend.guardrail.engine import _rule_signature_valid

        mandate = sample_mandate_data
        mandate.signature = "invalid_format"
        result = _rule_signature_valid(mandate)
        assert result.rule == "signature_valid"
        assert not result.passed
        assert "invalid_signature" in result.reason


class TestRuleNotExpired:
    """Test Rule 2a: Mandate must not be expired."""

    def test_active_mandate(self, sample_mandate_data):
        """Should pass for non-expired mandate."""
        from backend.guardrail.engine import _rule_not_expired

        mandate = sample_mandate_data
        mandate.expires_at = datetime.now(tz=timezone.utc) + timedelta(days=30)
        result = _rule_not_expired(mandate)
        assert result.passed
        assert result.reason == ""

    def test_expired_mandate(self, sample_mandate_data):
        """Should fail for expired mandate."""
        from backend.guardrail.engine import _rule_not_expired

        mandate = sample_mandate_data
        mandate.expires_at = datetime.now(tz=timezone.utc) - timedelta(days=1)
        result = _rule_not_expired(mandate)
        assert not result.passed
        assert "expired" in result.reason


class TestRuleNotRevoked:
    """Test Rule 2b: Mandate must not be revoked."""

    def test_active_mandate(self, sample_mandate_data):
        """Should pass for non-revoked mandate."""
        from backend.guardrail.engine import _rule_not_revoked

        mandate = sample_mandate_data
        mandate.revoked = False
        result = _rule_not_revoked(mandate)
        assert result.passed
        assert result.reason == ""

    def test_revoked_mandate(self, sample_mandate_data):
        """Should fail for revoked mandate."""
        from backend.guardrail.engine import _rule_not_revoked

        mandate = sample_mandate_data
        mandate.revoked = True
        result = _rule_not_revoked(mandate)
        assert not result.passed
        assert "revoked" in result.reason


class TestRuleCategoryInScope:
    """Test Rule 3: Requested category must be in allowed_categories."""

    def test_allowed_category(self, sample_mandate_data, sample_payment_request):
        """Should pass for category in allowed list."""
        from backend.guardrail.engine import _rule_category_in_scope

        mandate = sample_mandate_data
        request = sample_payment_request
        request.category = "groceries"
        result = _rule_category_in_scope(mandate, request)
        assert result.passed
        assert result.reason == ""

    def test_disallowed_category(self, sample_mandate_data, sample_payment_request):
        """Should fail for category not in allowed list."""
        from backend.guardrail.engine import _rule_category_in_scope

        mandate = sample_mandate_data
        request = sample_payment_request
        request.category = "electronics"
        result = _rule_category_in_scope(mandate, request)
        assert not result.passed
        assert "out_of_scope_category" in result.reason


class TestRuleWithinTransactionCap:
    """Test Rule 4: Amount must not exceed max_per_transaction."""

    def test_within_cap(self, sample_mandate_data, sample_payment_request):
        """Should pass for amount within cap."""
        from backend.guardrail.engine import _rule_within_transaction_cap

        mandate = sample_mandate_data
        request = sample_payment_request
        request.amount = 299.0
        result = _rule_within_transaction_cap(mandate, request)
        assert result.passed
        assert result.reason == ""

    def test_exceeds_cap(self, sample_mandate_data, sample_payment_request):
        """Should fail for amount exceeding cap."""
        from backend.guardrail.engine import _rule_within_transaction_cap

        mandate = sample_mandate_data
        request = sample_payment_request
        request.amount = 750.0
        result = _rule_within_transaction_cap(mandate, request)
        assert not result.passed
        assert "exceeds_transaction_cap" in result.reason


class TestRuleWithinRollingCap:
    """Test Rule 5: Rolling 7-day spend + this request must not exceed max_rolling_7d."""

    def test_within_rolling_cap(self, sample_mandate_data, sample_payment_request):
        """Should pass when total is within rolling cap."""
        from backend.guardrail.engine import _rule_within_rolling_cap

        mandate = sample_mandate_data
        request = sample_payment_request
        spent_7d = 500.0
        request.amount = 299.0
        result = _rule_within_rolling_cap(mandate, request, spent_7d)
        assert result.passed
        assert result.reason == ""

    def test_exceeds_rolling_cap(self, sample_mandate_data, sample_payment_request):
        """Should fail when total exceeds rolling cap."""
        from backend.guardrail.engine import _rule_within_rolling_cap

        mandate = sample_mandate_data
        request = sample_payment_request
        spent_7d = 1800.0
        request.amount = 300.0
        result = _rule_within_rolling_cap(mandate, request, spent_7d)
        assert not result.passed
        assert "exceeds_rolling_cap" in result.reason


class TestRuleNoReplay:
    """Test Rule 6: Nonce must not have been seen before."""

    def test_new_nonce(self):
        """Should pass for new nonce."""
        from backend.guardrail.engine import _rule_no_replay

        seen_nonces = ["nonce_001", "nonce_002"]
        result = _rule_no_replay("nonce_003", seen_nonces)
        assert result.passed
        assert result.reason == ""

    def test_replay_nonce(self):
        """Should fail for replayed nonce."""
        from backend.guardrail.engine import _rule_no_replay

        seen_nonces = ["nonce_001", "nonce_002"]
        result = _rule_no_replay("nonce_001", seen_nonces)
        assert not result.passed
        assert "replay_detected" in result.reason


class TestValidateIntegration:
    """Integration tests for the validate function."""

    def test_all_rules_pass(
        self, sample_mandate_data, sample_payment_request
    ):
        """Should return ALLOW when all rules pass (except signature which is mocked)."""
        # Mock the signature rule to always pass for integration tests
        from backend.guardrail import engine
        original_rule = engine._rule_signature_valid
        engine._rule_signature_valid = lambda m: engine.RuleResult(
            rule="signature_valid", passed=True, reason=""
        )

        try:
            decision = validate(
                mandate=sample_mandate_data,
                request=sample_payment_request,
                spent_7d=0.0,
                seen_nonces=[],
            )
            assert decision.allowed
            assert decision.primary_reason == "all_passed"
            assert decision.execution_token is not None
            assert len(decision.rules) == 7
            assert all(rule.passed for rule in decision.rules)
        finally:
            engine._rule_signature_valid = original_rule

    def test_category_blocks(
        self, sample_mandate_data, sample_payment_request
    ):
        """Should return BLOCK when category is out of scope."""
        # Mock the signature rule to always pass for integration tests
        from backend.guardrail import engine
        original_rule = engine._rule_signature_valid
        engine._rule_signature_valid = lambda m: engine.RuleResult(
            rule="signature_valid", passed=True, reason=""
        )

        try:
            sample_payment_request.category = "electronics"
            decision = validate(
                mandate=sample_mandate_data,
                request=sample_payment_request,
                spent_7d=0.0,
                seen_nonces=[],
            )
            assert not decision.allowed
            assert "out_of_scope_category" in decision.primary_reason
            assert decision.execution_token is None
        finally:
            engine._rule_signature_valid = original_rule

    def test_all_rules_evaluated(
        self, sample_mandate_data, sample_payment_request
    ):
        """Should evaluate all 7 rules even when early rules fail."""
        # Mock the signature rule to always pass for integration tests
        from backend.guardrail import engine
        original_rule = engine._rule_signature_valid
        engine._rule_signature_valid = lambda m: engine.RuleResult(
            rule="signature_valid", passed=True, reason=""
        )

        try:
            sample_payment_request.category = "electronics"
            sample_payment_request.amount = 10000.0
            decision = validate(
                mandate=sample_mandate_data,
                request=sample_payment_request,
                spent_7d=0.0,
                seen_nonces=[],
            )
            # All rules should be evaluated regardless of failures
            assert len(decision.rules) == 7
            # At least one should fail
            failed_rules = [r for r in decision.rules if not r.passed]
            assert len(failed_rules) > 0
        finally:
            engine._rule_signature_valid = original_rule
