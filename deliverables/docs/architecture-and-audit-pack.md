# Architecture and audit pack

The index for anyone who has to defend a number this platform produced — an auditor, Finance, a board pack reviewer. Every claim below points at the code that enforces it and the test that proves it.

## The one rule

The arithmetic is plain Python (`backend/app/calc/engine.py`); the model may propose a change to exactly one field, Confidence Level, under a cap, with a citation, into a queue a person clears. The service that calls the model returns confidence factors and structurally cannot return a revenue figure (`app/services/proposals.py`, `EVIDENCE_FIELDS` — no revenue enters the bundle; `app/judgment/contract.py` — nothing outside the bounds can be constructed).

## Where each document lives

| What | Where |
|---|---|
| Build specification (Rev 01, the requirements) | `../docs/Opportunity_Tracking_Agent_Build_Specification.html` |
| Decision register (the provisional answers, adopted 2026-09-15) | `../docs/OT_Decision_Register_and_Claude_API_Purpose.md` |
| Architecture (planes, layers, memory, run) | `../docs/02-architecture/OppTrack_Complete_Architecture.html`, `OppTrack_Layer_Diagrams.html`, `Step5_Platform_Architecture.html` |
| Product surface (screens, connectors, MCP, API) | `../docs/02-architecture/OppTrack_Product_Surface.html` |
| Work breakdown (108 tasks) and its tracker | `../docs/02-architecture/OppTrack_Work_Breakdown.html`, `WBS.md` |
| Generated: rubric, parameters, rules, API/MCP | `docs/generated/*.md` (`python -m scripts.generate_docs`) |
| Guides | `reviewer-handbook.md`, `getting-started-sales-owners.md`, `connector-guide.md`, `rollout-and-training.md` |

## Reproducing a figure

1. **A row's revenue.** `GET /api/v1/opportunities/{id}` returns `sales_revenue_k` and `adjusted_revenue_k`; both are `compute_project_financials(engine_row(opp))`, the function `tests/test_calc_engine.py` proves reproduces the workbook's ProjectTrack tab exactly for all nine rows.
2. **A proposal.** `GET /api/v1/proposals/{id}` shows the rubric version label, every factor with its rule id, points, verbatim quote and the guard that accepted, clipped or rejected it, and the flags the bounds applied. The `confidence_event` row behind it carries the prompt version and model id.
3. **A decision.** `GET /api/v1/audit?opportunity_id=…` is the append-only stream: proposals, approvals, rejections (with reason and the factors disagreed with), overrides, state changes, findings. No route updates or deletes any of it, and the ORM refuses to (`app/db/immutable.py`, `tests/test_review_loop.py::test_audit_rows_cannot_be_updated_or_deleted_by_anyone`).
4. **A run.** `GET /api/v1/runs/{id}` is the ten-step trace as executed; `GET /api/v1/runs/{a}/compare/{b}` attributes every difference between two runs to a recorded version change or labels it unattributed (`tests/test_reproducibility_and_authz.py`).
5. **The workbook.** `python -m scripts.findings_report` reproduces the specification's twelve data-quality findings from `TrackF (1).xlsx` in one command and finds two the specification missed.

## What is enforced, and where

| Property | Enforced in | Proven by |
|---|---|---|
| One writable field, bounded, cited | `app/judgment/contract.py`, `reply_guards.py` | `tests/test_judgment_layer.py` |
| Forbidden status/stage pairings never enter | `app/services/intake.py` (V-b) | `tests/test_api_review.py`, `test_findings_engine.py` |
| Nobody approves their own proposal; region scope in SQL | `app/services/proposals.py`, `app/security/roles.py` | `tests/test_reproducibility_and_authz.py` |
| A close needs the close grant and a loss reason | `app/services/state_transitions.py`, `transitions.py` | `tests/test_transitions_and_ids.py` |
| Audit tables append-only, seven years | `app/db/immutable.py`, `services/retention.py` | `tests/test_review_loop.py`, `test_identity_and_memory.py` |
| Numbers and pricing never embedded | `app/memory/__init__.py::scrub` | `tests/test_identity_and_memory.py` |
| No self-registration; role from the provisioned row, not the token | `app/security/oidc.py`, `roles.py` | `tests/test_identity_and_memory.py` |
| Connector values never overwrite a human edit silently | `app/connectors/_framework.py` | `tests/test_connectors.py` |
| Live model failure never becomes a number | `app/judgment/rubric.py` (`JudgmentReplyError`) | `tests/test_judgment_layer.py`, `test_operations.py` |
| Western open weights only on the local path | `app/judgment/rubric.py::local_model_allowed` | `tests/test_operations.py` |
| Assistant figures traceable to a tool | `app/services/assistant_guard.py` | `tests/test_assistant_grounding.py` |

## Versions stamped on every event

Rubric version (label), prompt version (`2026.09-matrixB`), model id (or none for MOCK and for a human decision), calculation version (`calc-2026.09` on the ROI feed). A difference between two figures that does not map to one of these is the finding, and the comparison endpoint says so.

## Retention

Episodic memory (snapshots, runs, events, history) is immutable for seven years and never deleted by any job. Semantic memory expires after eight quarters unless preserved. A deleted account is anonymised; its decisions stay under its id. `python -m scripts.run_job retention` reports the state; `python -m scripts.backup` and `restore` are the drill.
