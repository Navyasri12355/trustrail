# TrustRail — Documentation Index

> Razorpay AI Buildathon · Track 01: AI Growth & Agentic Commerce

---

## Documents

| File | Purpose | Audience |
|---|---|---|
| [README.md](../README.md) | Project overview, how to run, architecture diagram | Anyone evaluating the project |
| [TrustRail_PRD.md](./TrustRail_PRD.md) | Original product requirements — problem, solution, goals, 4-week plan | Product / judging context |
| [uap-mapping.md](./uap-mapping.md) | Protocol comparison table: UCP / AP2 / UAP → TrustRail fields | Protocol fluency demonstration |
| [prd.json](./prd.json) | 15-story structured task list (Ralph-compatible format) | Build tracking / agent loop |
| [progress.txt](../progress.txt) | Build log — iteration history, patterns discovered, gotchas | Future contributors |

---

## Architecture Overview

```
docs/
├── index.md            ← you are here
├── TrustRail_PRD.md    ← product requirements
├── uap-mapping.md      ← protocol comparison table (submission asset)
└── prd.json            ← structured task list

backend/
├── main.py             ← FastAPI app + router wiring
├── requirements.txt    ← Python dependencies
├── crypto/keys.py      ← Ed25519 sign/verify + keygen CLI
├── db/
│   ├── models.py       ← Mandate + AuditLog ORM models
│   ├── database.py     ← Engine + SessionLocal + get_db()
│   └── init.py         ← Table creation script
├── guardrail/
│   ├── engine.py       ← 7-rule guardrail (pure Python, injectable)
│   └── audit.py        ← Hash-chained audit log writer
├── routes/
│   ├── manifest.py     ← GET /.well-known/ucp
│   ├── mandates.py     ← POST /mandates · DELETE /mandates/{id}
│   ├── pay.py          ← POST /pay (guardrail → Razorpay)
│   └── audit_log.py    ← GET /audit-log
└── adapters/
    ├── ucp.py          ← POST /adapters/ucp/checkout
    ├── ap2.py          ← POST /adapters/ap2/intent
    └── uap_ready.py    ← POST /adapters/uap/intent (documented stub)

frontend/src/
└── App.jsx             ← Reviewer dashboard (React + Vite)

agent/
└── harness.py          ← 7 adversarial scenarios (PRD Section 10)
```

---

## Key Design Decisions

### Why protocol-agnostic?
See `TrustRail_PRD.md §3`. UCP, AP2, and UAP all share the same conceptual
core (delegate → prove → enforce). TrustRail implements the core once and
exposes thin adapters per protocol, so adding UAP support when the spec ships
requires only updating `adapters/uap_ready.py`.

### Why rule-based (not LLM) enforcement?
Scenario 7 in `agent/harness.py` is the proof: prompt injection in a merchant
catalog cannot bypass the guardrail because the engine reads mandate rules,
not catalog text. "Asking the LLM nicely" is not a security model.

### Why hash-chained audit log?
Each row's SHA-256 covers the previous row's hash. Tampering with any
historical entry breaks all subsequent hashes — detectable at a glance.
See `backend/guardrail/audit.py` and `progress.txt §PATTERNS`.

---

## Quick Links

- API docs (Swagger): http://localhost:8000/docs
- Reviewer dashboard: http://localhost:5173
- Protocol comparison: [uap-mapping.md](./uap-mapping.md)
