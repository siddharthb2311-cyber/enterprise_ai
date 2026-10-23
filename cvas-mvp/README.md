# CVAS MVP — Complaint Verification & Automated Settlement (Phase 1)

This is the Phase 1 MVP from the execution roadmap: one end-to-end pipeline,
one vertical ("item missing" / "item damaged" in quick-commerce), one tenant.

Scope, deliberately:
- Complaint intake API + evidence upload
- Evidence store (Postgres for structured data, local/S3-compatible object storage for media)
- Verification engine v1 — pluggable interface, ships with a rule-based + mock-model
  implementation so the pipeline runs end-to-end without needing real model access yet
- Decision engine v1 — weighted composite score, three buckets (auto_approve /
  auto_reject / review), thresholds configurable per tenant
- Append-only audit log for every state transition
- Merchant-facing review queue endpoint — **no auto-settlement yet**. Phase 1
  outputs a recommendation; a human/merchant system executes it. Settlement
  automation is Phase 3 in the roadmap.

## Quickstart

```bash
cp .env.example .env
docker compose up --build
```

API docs: http://localhost:8000/docs

## Architecture (this MVP)

```
Client / SDK  →  POST /v1/complaints        (intake)
              →  POST /v1/complaints/{id}/evidence   (photos, telemetry)
Order system  →  POST /v1/webhooks/order-events       (ground truth push)
                        │
                        ▼
              VerificationEngine.run(complaint)
                 - classify complaint type (LLM stub)
                 - check evidence consistency (vision stub)
                 - compute fraud signals (velocity, duplicate hash)
                        │
                        ▼
              DecisionEngine.decide(complaint, signals)
                 - composite score = Σ(weight_i × signal_i)
                 - bucket: auto_approve | auto_reject | review
                        │
                        ▼
              AuditLog.record(every step)
                        │
                        ▼
Merchant dashboard  ←  GET /v1/decisions/{id}
                        GET /v1/queue/review
```

## Swapping in real models

`app/services/verification_engine.py` defines `VerificationEngine` with three
swappable hooks:

- `classify_complaint(text)` → currently a keyword-based stub. Replace with an
  LLM call (e.g. Claude) that returns `{category, confidence}`.
- `check_image_consistency(image_path, order_context)` → currently a stub that
  always returns a neutral score. Replace with a vision model call for
  damage/count detection and perceptual-hash duplicate lookup.
- `fraud_signals(user_id, device_id, complaint)` → real logic already implemented
  against the `RiskProfile` table (claim velocity, refund ratio). Extend with
  geo-velocity and cross-tenant graph lookups in Phase 2/6.

Nothing else in the pipeline needs to change when you swap these — the
`Decision`/`Complaint`/`AuditEvent` contracts stay the same.

## Data model

See `app/models.py`. Matches the entity table from the architecture doc:
`Complaint`, `Evidence`, `VerificationResult`, `RiskProfile`, `Decision`,
`AuditEvent`. `Settlement` table exists but is unused until Phase 3.

## Running tests

```bash
pip install -r requirements.txt
pytest
```
