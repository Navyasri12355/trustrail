# TrustRail Protocol Comparison: UCP / AP2 / UAP → Internal Mandate Fields

> **Honesty note:** This table maps TrustRail's internal mandate schema against
> three agentic commerce protocols. UCP and AP2 are real, published (draft) specs.
> UAP (NPCI Unified Agent Protocol) has **no public spec as of August 2026** —
> every UAP row is derived from public reporting and industry sources, and is
> labeled accordingly. This document is a design artifact, not a compliance claim.

---

## Field Mapping Table

| TrustRail Internal Field | UCP Mapping | AP2 Mapping | UAP Mapping | UAP Status |
|---|---|---|---|---|
| `mandate_id` | Implicit per checkout session | `credential.mandate_id` | `delegation_id` | **ANTICIPATED** |
| `issuer_user_id` | Buyer identity in checkout context | `credential.issuer_did` (DID) | `delegator_vpa` (UPI VPA) | **CONFIRMED** (UPI identity model) |
| `agent_id` | `buyer_agent.agent_id` | `credential.agent_did` | `agent_registry_id` (NPCI registry) | **ANTICIPATED** (agent registry reported) |
| `merchant_id` | Served from `/.well-known/ucp` manifest | `credential.merchant_id` | `merchant_vpa` (UPI VPA) | **CONFIRMED** (UPI merchant model) |
| `allowed_categories` | `item.category` (per-request, not pre-scoped) | `credential.scope.permitted_categories` | Spend category limits | **CONFIRMED** ("category limits" in reports) |
| `max_per_transaction` | No pre-scoped limit in UCP; merchant sets price | `credential.scope.max_single_txn_inr` | Per-transaction cap | **CONFIRMED** ("spend limits" in reports) |
| `max_rolling_7d` | Not in UCP spec | `credential.scope.max_7d_window_inr` | Rolling window cap | **CONFIRMED** ("rolling window" reported) |
| `currency` | Implicit from merchant manifest | `credential.scope.currency` | INR (UPI is INR-only) | **CONFIRMED** |
| `issued_at` / `expires_at` | Session-scoped, no explicit expiry field | `credential.issued_at` / `expires_at` | Token validity window | **ANTICIPATED** |
| `revoked` | No revocation model in UCP | Not in AP2 draft | Human-revocable (reported requirement) | **CONFIRMED** ("review if something goes wrong") |
| `signature` | No mandate-level signing in UCP | `credential.proof` (W3C VC proof) | NPCI-issued token signature | **ANTICIPATED** |
| `protocol_origin` | `"ucp"` | `"ap2"` | `"uap_ready"` | N/A (TrustRail internal) |
| `audit_trail` | Not in UCP spec | Not in AP2 draft | "Should be able to review it" (verbatim) | **CONFIRMED** (direct quote from NPCI sources) |
| Agent registry | Not required | Not required | NPCI pre-registration required | **ANTICIPATED** (reported design intent) |
| Human dispute UI | Not in UCP spec | Not in AP2 draft | Explicit requirement | **CONFIRMED** (dispute model reported) |

---

## Protocol Summary

### UCP (Universal Commerce Protocol)
- **Backed by:** Google
- **Primary purpose:** Agent-facing catalog discovery via `/.well-known/ucp` manifests
- **Mandate model:** Loose — no pre-issued signed mandate; the agent discovers what's available and sends a checkout request
- **TrustRail integration:** UCP adapter adds the missing mandate layer on top of UCP's discovery mechanism
- **Spec status:** Published draft

### AP2 (Agent Payments Protocol)
- **Backed by:** Google
- **Primary purpose:** Cryptographically verifiable mandates — signed statements of intent so a payment processor can prove an agent was authorized to spend
- **Mandate model:** Strong — W3C Verifiable Credential with issuer proof
- **TrustRail integration:** AP2 credential maps cleanly to TrustRail's mandate schema; AP2's VC proof replaces our Ed25519 signature in production
- **Spec status:** Published draft (2025)
- **Stand-in note:** TrustRail uses Ed25519 as a stand-in for AP2's VC proof scheme. In production, replace `verify_signature()` in `ap2.py` with a W3C VC verifier.

### UAP (Unified Agent Protocol — NPCI / India)
- **Backed by:** NPCI (National Payments Corporation of India)
- **Primary purpose:** Let AI agents transact over UPI on a user's behalf under RBI-approved delegation rules
- **Mandate model:** Delegation token issued by NPCI, scoped to spend limits and categories
- **TrustRail integration:** `uap_ready.py` stub maps UAP anticipated fields to TrustRail internal schema
- **Spec status:** **No public spec.** RBI approval pending as of August 2026.
- **Key reported requirements (CONFIRMED):** Spend/category limits, human-reviewable logs, dispute model, rolling window caps
- **Key design elements (ANTICIPATED):** NPCI agent registry, token signature scheme, delegation ID format, VPA-based identity

---

## Why Protocol-Agnostic Matters

Every protocol above has the same conceptual core:

```
Human delegates spend authority → Agent presents proof → Merchant validates → Payment executes
```

TrustRail implements this core **once** and exposes thin adapters for each wire protocol.
When UAP ships, only `uap_ready.py` needs updating — the guardrail engine, audit trail,
and mandate schema are already UAP-compatible by design.

---

## References

- UCP spec: https://developers.google.com/commerce/agent-payments/ucp
- AP2 spec: https://developers.google.com/commerce/agent-payments/ap2
- UAP public reporting: NPCI industry briefings (August 2026); no public URL available
- TrustRail guardrail rules: `backend/guardrail/engine.py`
- TrustRail mandate schema: `backend/db/models.py` + PRD Section 6.2
