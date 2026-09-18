# AGENTS.md

Instructions for coding agents working in this repository. **This directory
(`opportunity_tracking_agent/`) is the repository root** — `.github/workflows/`
lives directly under it, and every relative path in CI and the deploy tooling
is written relative to here, not to `deliverables/`.

## What this is

OppTrack: a design-win opportunity pipeline tracker (intake → confidence
judgment → human review → forecast). FastAPI + SQLAlchemy backend, React +
Vite frontend, deterministic calc engine with an LLM-assisted judgment layer
behind a mandatory human approval gate. The real, shipped implementation
lives under `deliverables/`; `opptrack_poc/` is an earlier validated
reference for the calc/judgment split (kept for provenance, not run in
anger) and `prototypes/` is static HTML mockups.

Read [`deliverables/README.md`](deliverables/README.md) first — it's the
canonical map of the codebase (directory-by-directory) and is kept current.
This file is about *working in* the repo, not describing it a second time.

## Repository layout

```text
AGENTS.md                    this file
.github/workflows/           ci.yml (tests + build on push/PR), deploy-pages.yml (GitHub Pages)
docs/                         requirements, architecture HTML docs, correspondence, decision register
data/TrackF (1).xlsx          the canonical reference workbook -- see "Before you push" below
opptrack_poc/                 earlier validated calc/judgment prototype, not the running app
prototypes/                   static HTML UI mockups
deliverables/                 the real app -- see deliverables/README.md for the full map
  backend/                    FastAPI + SQLAlchemy, plain venv or Docker
  frontend/                   React + Vite SPA
  deploy/                     production deployment overlay -- see deploy/README.md
  docker-compose.yml          full stack (Postgres, Redis, MinIO, API, scheduler, SPA, optional vLLM)
  docs/                       generated docs, walkthroughs, handbooks
  WBS.md                      108-task work breakdown, living status tracker
```

## Setting up and running it locally

No Docker needed for local work — everything defaults to an in-process
stand-in (SQLite, fakeredis, on-disk object storage, mock judgment). See
`deliverables/backend/app/core/config.py` for every setting and its default.

```bash
# backend
cd deliverables/backend
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload &     # http://127.0.0.1:8000/docs

# frontend, in a second shell
cd deliverables/frontend
npm install
cp .env.local.example .env.local
npm run dev &                        # http://127.0.0.1:5173
```

On Windows, `deliverables/scripts/dev_up.ps1` does both at once (`-Mode
local` for the real sign-in flow at :5180, `-Mode headers` for five
pre-signed-in per-role apps at :5181-5185) and writes logs to
`deliverables/logs/`.

## Testing and verification

```bash
cd deliverables/backend
pytest -q                              # ~374 tests, plain SQLite in-memory, no external services
python -m scripts.findings_report      # Phase 0: reproduces the workbook's 12 documented findings
python -m scripts.walkthrough          # builds docs/walkthrough.md from the real workbook into a fresh DB
python -m scripts.generate_docs        # regenerates deliverables/docs/generated/*.md from the code
alembic upgrade head && alembic downgrade base && alembic upgrade head   # migrations round-trip

cd deliverables/frontend
npx tsc --noEmit -p tsconfig.json      # typecheck
npm run build                          # tsc -b && vite build
```

There is no frontend unit/integration test suite — verification is
typecheck + build + (optionally) `python -m scripts.ui_test`, which drives
the real UI in Chrome via Playwright as all five roles and writes
screenshots to `deliverables/ui-report/`. `.github/workflows/ci.yml` is the
authoritative list of what must pass before a change is done; run its
steps locally before calling something finished, the same way you would in
any repo with CI.

**No browser available in some sandboxes.** If you can't launch Chrome to
actually look at a UI change, say so explicitly rather than claiming it
renders correctly — typecheck and build passing is not the same as the
feature working.

## Auth modes — know which one you're in

Three modes, selected by the backend's `AUTH_MODE` and reported to the UI at
`GET /api/v1/auth/config`:

| Mode | How a caller becomes an actor | Where it's used |
|---|---|---|
| `headers` (default) | `X-OppTrack-Actor/Role/Regions` request headers, **no password, no real auth** | tests, `dev_up.ps1 -Mode headers` |
| `local` | email + password + one-time code, revocable sessions (`/api/v1/auth/*`) | `dev_up.ps1` default; required for any public deployment |
| OIDC (`AUTH_ISSUER` set) | Bearer token from an identity provider | not yet wired up anywhere real |

**`headers` mode is not a security boundary.** It's stated in
`app/security/roles.py`'s own docstring and on the Users & Access screen.
Never treat an `X-OppTrack-Role` header as proof of anything when reasoning
about what's "secure" in this codebase — it's a dev stand-in, full stop.

Role and region scope always come from the admin-provisioned `app_user` row
for an email, never from the credential itself — signing up (in `local`
mode) creates a login, not access.

## Things that will bite you if you don't know them

- **`/dev/*` is deliberately unauthenticated** (`deliverables/backend/app/api/v1/dev.py`)
  — a live DB table browser and log tailer, gated only by
  `Settings.dev_tools_enabled` (default `true`). Fine locally; a public
  deployment's compose overlay sets it to `false`. Don't add anything
  sensitive to that router without keeping that gate, and don't flip the
  default in `config.py` without updating `deliverables/deploy/docker-compose.prod.yml`
  to match.
- **CORS** (`app/main.py`) only locks down to `CORS_ORIGINS` when either
  `AUTH_ISSUER` (OIDC) or `AUTH_MODE=local` is set *and* `CORS_ORIGINS` is
  non-empty; otherwise it's wide open (`*`) by design, since the dev header
  stand-in has no credential worth protecting via CORS anyway.
- **Direct UI entry is the primary intake path, not the TrackF workbook.**
  Workbook/CSV import (`/import`) is migration and backfill only — don't
  design a feature that assumes the workbook is the source of truth for new
  rows.
- **Judgment is deterministic-first.** The calc engine (`app/calc/`) is
  plain Python; the model (`app/judgment/`) may only propose a change to
  *one* field (Confidence Level), under a cap, with a citation, into a human
  review queue. Don't let a "helpful" change let a model write anything else
  directly.
- **Decisions are tracked, not assumed.** `docs/OT_Decision_Register_and_Claude_API_Purpose.md`
  and `deliverables/WBS.md` are the record of what's been decided and what's
  still open (e.g. Matrix A baseline confidence is unratified — that's why
  it ships as an empty grid, not a guess). If a task depends on something
  marked open there, say so rather than picking a default silently.
- **Comment style**: this codebase writes almost no comments, and the ones
  that exist explain a non-obvious *why* (a decision number, a WBS
  reference, a workaround), never *what* the code does. Match that — don't
  add narrating comments to well-named code.

## Deploying

Local Docker Compose (`deliverables/docker-compose.yml`) is a full stack
demo — Postgres+pgvector, Redis, MinIO, API, scheduler, the SPA behind
nginx, an optional vLLM profile — but is **not** safe to expose publicly as-is
(default `AUTH_MODE=headers`, `/dev/*` open). For a public-IP deployment,
use `deliverables/deploy/` — a production overlay (TLS edge proxy via
Caddy, locked-down auth/CORS/dev-tools, a first-admin bootstrap script,
a GitHub Pages workflow for a separately-hosted UI) with a full manual
runbook in [`deliverables/deploy/README.md`](deliverables/deploy/README.md).
Read that file before changing anything under `deploy/` or
`docker-compose.yml`'s port bindings — several of the current settings
(loopback-only ports, `DEV_TOOLS_ENABLED`) exist specifically to make the
public path safe by default and are easy to silently undo.

## Before you push this anywhere

This repo is not yet connected to a git remote. Before it is:
check whether `data/TrackF (1).xlsx` or anything under `docs/` (customer
correspondence, pricing) is real business data you don't want in git
history — see the `.gitignore` at the repo root and
`deliverables/deploy/README.md` §7 for what to do about it. Don't assume
it's safe to publish just because it's already in the working tree.
