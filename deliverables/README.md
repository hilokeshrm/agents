# OppTrack Deliverables

The real platform implementation, following the stack and layering fixed in
[`../docs/02-architecture/OppTrack_Complete_Architecture.html`](../docs/02-architecture/OppTrack_Complete_Architecture.html)
and the task order in [`../docs/02-architecture/OppTrack_Work_Breakdown.html`](../docs/02-architecture/OppTrack_Work_Breakdown.html).
This supersedes `../opptrack_poc/`, which stays in place as the validated reference
for the calc/judgment split (see `app/calc/engine.py` and `app/judgment/rubric.py`
below, ported from it).

Direct in-UI entry is the primary intake path, not the TrackF workbook — see
`frontend/app/intake/`. Workbook/CSV import is migration and backfill only.

## Layout

```text
backend/            FastAPI + SQLAlchemy -- runs on a plain venv, no Docker
  app/
    api/v1/          REST: opportunities, review (proposals, runs, compare, audit), rubric (versions,
                      publish-v1, feedback), analyses (+ targets, actuals, sweeps, notifications, jobs,
                      metrics), imports (dry run, commit, workbook report), connectors (pulls,
                      reconciliation), webhooks (+ exports, ROI feed), users (provisioning), assistant,
                      accounts, products, contacts, reports, dashboard, scenarios, registry, access, dev
    calc/            deterministic calc engine, NRE splitter and NRE by quarter, phasing rule, severity
    analysis/        Layer 4: discovering registry + nine analyses (six live, three waiting on data)
    judgment/        Matrix B rule table, the ConfidenceProposal contract, the rubric (MOCK / Anthropic / vLLM),
                      ten reply guards
    guards/          validation rules V-a..V-i and the Phase 0 findings report
    intake/          workbook reader, coercion, canonicalisation, provenance, milestones, the intake schema
    connectors/      framework (precedence ladder, reconciliation), CRM, ERP, distributor POS, market data
    memory/          L3 semantic memory: scrub, chunk, expire, the evidence assembler
    security/        six roles and region scope in SQL; OIDC bearer tokens and service-account keys
    services/        intake, proposals, judgment runs, transitions (lifecycle proposals), portfolio (C12),
                      rubric versions, calibration, run compare, notifications and sweeps, webhooks,
                      scheduler (eight jobs), metrics and quota, retention, backup, snapshots, assistant
    mcp/             the MCP server over the assistant's read-only tools
    db/              24 tables, append-only enforcement for the audit ones, session
  alembic/            migrations 0001-0009
  scripts/            findings_report, walkthrough, ui_test, run_job / scheduler, backup, backfill_real_data, backfill_ids, generate_docs
  tests/              357 tests
  Dockerfile

frontend/            React + Vite SPA (design ported from prototypes/opportunity_tracker.html); nginx.conf, Dockerfile
  src/components/    Dashboard (with per-role landing), Pipeline, Intake, Review queue, Roll-ups, Runs & audit
                      (with run comparison), Import, Findings, Analyses (+ targets), Connectors (+ reconciliation),
                      Notices, Rubric & Matrix A (+ feedback), Users, Access, Ask OppTrack (also at /embed/assistant)

docs/                walkthrough (generated), reviewer-handbook, getting-started-sales-owners, connector-guide,
                     architecture-and-audit-pack, rollout-and-training, generated/ (rubric, parameters, rules, API+MCP)
docker-compose.yml   Postgres (pgvector), Redis, MinIO, API, scheduler, SPA, optional vLLM profile
deploy/              production overlay for a public-IP host -- TLS edge proxy, locked-down auth/CORS/dev-tools,
                     first-admin bootstrap, GitHub Pages workflow; see deploy/README.md for the full runbook
WBS.md               the 108-task tracker
```

No Docker for now. Everything defaults to running in-process on a plain Python
venv (see `app/core/config.py`):

- **Database** -- SQLite (`opptrack.db`), no Postgres server. Point `DATABASE_URL`
  at a real `postgresql+psycopg://...` URL later (`pip install ".[postgres]"` first);
  nothing in `app/db/` is SQLite-specific.
- **Redis** -- `fakeredis`, an in-process pure-Python stand-in, no server. Set
  `REDIS_BACKEND=real` once an actual Redis instance exists.
- **Object storage** -- writes to `backend/data/objects/` on disk, no S3/MinIO. Set
  `STORAGE_BACKEND=s3` once a real S3-compatible endpoint exists.
- **Identity** -- request headers stand in for SSO until `AUTH_ISSUER` is set; then
  every request needs a Bearer token from that issuer or a service account's API key.
- **Model** -- `JUDGMENT_MODE=mock` (rule-based scorer over the same Matrix A) until the
  security sign-off for hosted use exists; then `live` with `JUDGMENT_BACKEND=anthropic`
  or `vllm` (Western open weights only).

## Running locally

```bash
# backend
cd backend
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload > ../logs/backend.log 2>&1 &
pytest                               # 357 tests
python -m scripts.findings_report    # Phase 0: the workbook's twelve documented findings, generated
python -m scripts.run_job --crontab  # the eight scheduled jobs as cron lines
python -m scripts.generate_docs      # docs/generated/*.md from the code
python -m scripts.walkthrough        # docs/walkthrough.md: the demo, from the workbook into a fresh DB
python -m scripts.seed_demo_accounts # five demo people for the sign-in screens (password OppTrack-2026!)
python -m scripts.ui_test            # drives the real UI in Chrome as all five roles (pip install playwright;
                                     #   needs Chrome and the frontend's node_modules); screenshots in ui-report/

# frontend
cd frontend
npm install
cp .env.local.example .env.local
npm run dev > ../logs/frontend.log 2>&1 &
```

## Signing in

Three identity modes, chosen by the backend's `AUTH_MODE` (`GET /api/v1/auth/config` tells the UI):

| Mode | How a caller becomes an actor | Use |
|---|---|---|
| `headers` (default) | `X-OppTrack-Actor/Role/Regions` request headers, no password | tests, `scripts\dev_up.ps1 -Mode headers` (one pre-signed-in app per role) |
| `local` | email + password, one-time code by email, revocable sessions (`/api/v1/auth/*`) | `scripts\dev_up.ps1` (default): landing page, sign-up, sign-in at http://127.0.0.1:5180/ |
| OIDC (`AUTH_ISSUER` set) | a Bearer token from the identity provider | production (WBS 9.4) |

In every mode the **role and region scope come only from the admin-provisioned `app_user` row** for that
email (Users screen). Signing up creates a credential, not a role: a verified account with no row sees
"waiting for a role" until an admin provisions the email.

One-time codes: `OTP_DELIVERY=console` (default) writes the code to `logsackend.log` and shows it on the
verify screen; `OTP_DELIVERY=smtp` sends it. For Gmail, in `backend\.env`:

```
OTP_DELIVERY=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx    # a Google App Password (Account > Security > 2-Step Verification), not the account password
SMTP_SENDER=you@gmail.com
```

Manual test cases for every role and screen: [docs/manual-test-plan.md](docs/manual-test-plan.md).

## Dev Tools

`/dev` (linked from the top-right of every page, not the main product nav) —
browses every real DB table live via SQLAlchemy's inspector (`app/api/v1/dev.py`;
a new model needs no change there to show up) and tails the actual backend/
frontend process output from `logs/backend.log` / `logs/frontend.log` (gitignored;
only exist once you redirect the dev servers there, as above). Unauthenticated —
local debugging only, never deploy this router past a local machine.

## Status

See [`WBS.md`](WBS.md) — a living, greppable mirror of the 108-task Work Breakdown
Structure, updated in place as tasks land here. Highlights:

**The UI is complete against package 10.0's screen list** — every screen that
package names except the two machine surfaces (10.12 MCP, 10.13 webhooks/exports).
Seventeen routes, all live against the real API, no mock data anywhere:

| Screen | Route | What is real behind it |
|---|---|---|
| Per-role landing | `/` | Five different landings; the role changes what the page is *for*, not just which buttons are enabled |
| Opportunities | `/dashboard` | Provenance-aware list with a Matrix A baseline column — a deviation report once a grid is published |
| Stage board | `/stage-board` | Kanban by hardware Stage; a move writes a `state_history` row |
| Opportunity | `/opportunities/[id]` | Path, Details, **Judgment** (every proposal, factor by factor), **Provenance** (per-ParamSpec source and trust), Activity, Related |
| Review queue | `/review` | Approve / override / reject, each writing an audit event; rejected and not-assessable factors shown, not tidied away |
| Runs & audit | `/runs`, `/runs/[id]` | The ten-step trace as executed and stored, plus the append-only feed over `confidence_event`, `state_history` and `finding` |
| Import | `/import` | Upload → sealed snapshot → dry-run findings → commit the rows that passed |
| Roll-ups | `/roll-ups` | Forecast feed by quarter, region roll-up, queue what-if, CSV export |
| Assistant | `/assistant` | Nine read-only tools; no write tool exists, and the page says so from the API's own report |
| Rubric & Matrix A | `/admin/rubric` | Draft → impact preview → publish a version every later proposal cites |
| Users & access | `/admin/access` | The permission matrix served from the copy the API enforces, and the six enforcement points with what is built at each |
| Accounts / Contacts / Products / Reports / Dashboards / Intake / Dev | | as before |

**What each screen refuses to invent** is the point, and it is visible on the
screen rather than buried here: Matrix A ships as an empty grid because baseline
confidence is unratified (WBS 1.1 Q1); the factor cap is unset, so nothing is
clipped until someone publishes a version that says to; steps 4 and 8 of every
run report *skipped* with the reason; the forecast feed states that the quarterly
phasing rule is undecided and reports unphased rows rather than assigning them;
Users & access shows the identities the data actually contains instead of a
fabricated user roster; and the assistant, with no model key configured, answers
what it recognises and says plainly when it does not.

**Access control is real except for its identity source.** The permission matrix
(`app/security/roles.py`) is the product document's table cell for cell, and it is
enforced at three of the six points that document names: the route (a dependency
asserts the role before the handler runs), the query (region scope wraps the
SELECT, so an out-of-scope row is a 404 rather than a filtered response), and the
decision (a reviewer cannot resolve a row they own — checked in code, not in the
interface). What is *not* real is where the identity comes from: SSO is WBS 9.4
and does not exist, so role and region scope arrive as request headers set by the
switcher in the top bar. That is stated in the module docstring, on the Users &
access screen and in the switcher itself. **It is not a security boundary today.**

**Done, and proven against the real `TrackF (1).xlsx` / field-map doc, not
synthetic data:**

- **2.2 Canonical enums**, **3.3 Coercion**, **3.4 Canonicalisation**, **3.5 NRE
  line splitter**, **4.2 Blocking vs advisory severity**, **6.3 Milestone
  extractor** — each tested by reading the actual workbook and confirming a
  real, cited fact (spelling variants collapsing, the file's own `Sop'26` typo
  caught twice, the exact 7/10 NRE split, the five skeleton rows excluded
  without diluting the nine-row total).
- **3.6 Provenance wrapper**, **5.2 (C3-C7)**, **5.7 Scenario recompute** — same
  rigor, and all three now have a screen reading them.

**Done, mechanism only (no real data source exists yet to prove against):**

- **9.1** DB schema (twelve tables), **9.2** state_history event stream, **9.6**
  Redis/object storage, and the judgment machinery: **the eight reply guards**,
  **the ten-step run**, **rubric versioning**.

**Partial — real and working end to end, built ahead of formal dependencies:**

- **10.2–10.11** (every screen above), **9.5** (roles and scope, identity
  pending 9.4), **2.3** (versioning built, contents blocked on 1.1), **8.1**
  (queue and human gate), **4.6** (dry run, pending 4.1's rule set), **2.1**
  ParamSpec registry, **2.5** `runnable()`, **2.6** reason codes (the override
  vocabulary is now enforced for real at the API), **3.2** Snapshot writer,
  **9.8** one-time backfill, **10.1** API gateway.

Everything else — 4.1's V-a..V-i rules, 6.2's six live analyses, L3/L5 memory,
MCP tools, connectors, SSO, deployment — is stubbed to the target structure or
not started, and the screens that would consume it say so on their face.

**Test suite:** 195 backend tests (`pytest`), `npx tsc --noEmit` clean across the
frontend, and every route checked on the running app.
