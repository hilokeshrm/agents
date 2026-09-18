# API and MCP reference

Generated from the running OpenAPI document (`/openapi.json`, version 0.2.0). Identity: a Bearer token from the configured OIDC issuer, a service account's `X-OppTrack-Api-Key`, or -- in development only -- the `X-OppTrack-Role` / `X-OppTrack-Regions` / `X-OppTrack-Actor` headers. Every response carries `X-Request-ID`.

## access

| Route | What it does |
|---|---|
| `GET /api/v1/access/actors` | Actors |
| `GET /api/v1/access/matrix` | Matrix |
| `GET /api/v1/access/me` | Me |

## accounts

| Route | What it does |
|---|---|
| `GET /api/v1/accounts/{name}` | Get Account |
| `GET /api/v1/accounts` | List Accounts |

## analyses

| Route | What it does |
|---|---|
| `GET /api/v1/actuals` | List Actuals |
| `GET /api/v1/analyses/catalogue` | Catalogue |
| `GET /api/v1/analyses` | Analyses |
| `GET /api/v1/jobs` | List Jobs |
| `GET /api/v1/metrics/prometheus` | Metrics Prometheus |
| `GET /api/v1/metrics` | Metrics |
| `GET /api/v1/notifications` | List Notifications |
| `GET /api/v1/targets` | List Targets |
| `POST /api/v1/jobs/{name}/run` | Run Scheduled Job |
| `POST /api/v1/notifications/dispatch` | Dispatch |
| `POST /api/v1/sweeps/nightly` | Run Nightly Sweep |
| `PUT /api/v1/targets` | Set Target |

## analytics

| Route | What it does |
|---|---|
| `GET /api/v1/analytics/win-rate` | Get Win Rate |

## assistant

| Route | What it does |
|---|---|
| `GET /api/v1/assistant/embed` | Embed |
| `GET /api/v1/assistant/history` | History |
| `GET /api/v1/assistant/surface` | Surface |
| `POST /api/v1/assistant/ask` | Ask Question |

## auth

| Route | What it does |
|---|---|
| `GET /api/v1/auth/config` | Config |
| `GET /api/v1/auth/session` | Session |
| `POST /api/v1/auth/login` | Login |
| `POST /api/v1/auth/logout` | Logout |
| `POST /api/v1/auth/resend` | Resend |
| `POST /api/v1/auth/reset/finish` | Reset Finish |
| `POST /api/v1/auth/reset/start` | Reset Start |
| `POST /api/v1/auth/signup` | Signup |
| `POST /api/v1/auth/verify` | Verify |

## connectors

| Route | What it does |
|---|---|
| `GET /api/v1/connectors/reconciliation` | Reconciliation Queue |
| `GET /api/v1/connectors` | List Connectors |
| `POST /api/v1/connectors/{name}/pull` | Pull |

## contacts

| Route | What it does |
|---|---|
| `DELETE /api/v1/contacts/{contact_id}` | Delete Contact |
| `GET /api/v1/contacts` | List Contacts |
| `POST /api/v1/contacts` | Create Contact |

## dashboard

| Route | What it does |
|---|---|
| `GET /api/v1/dashboard` | Get Dashboard |

## dev

| Route | What it does |
|---|---|
| `GET /api/v1/dev/logs/{source}` | Get Log |
| `GET /api/v1/dev/tables/{table_name}` | Get Table |
| `GET /api/v1/dev/tables` | List Tables |

## imports

| Route | What it does |
|---|---|
| `GET /api/v1/imports/workbook-report` | Workbook Report Endpoint |
| `GET /api/v1/imports/{snapshot_id}/findings` | Snapshot Findings |
| `GET /api/v1/imports` | List Snapshots |
| `POST /api/v1/imports/dry-run` | Dry Run |
| `POST /api/v1/imports/{snapshot_id}/commit` | Commit |

## opportunities

| Route | What it does |
|---|---|
| `GET /api/v1/opportunities/{opportunity_id}/owner-history` | Get Owner History |
| `GET /api/v1/opportunities/{opportunity_id}/provenance` | Get Provenance |
| `GET /api/v1/opportunities/{opportunity_id}/state-history` | Get State History |
| `GET /api/v1/opportunities/{opportunity_id}/time-in-stage` | Get Time In Stage |
| `GET /api/v1/opportunities/{opportunity_id}` | Get Opportunity |
| `GET /api/v1/opportunities` | List Opportunities |
| `POST /api/v1/opportunities/{opportunity_id}/owner` | Change Owner |
| `POST /api/v1/opportunities/{opportunity_id}/transition` | Transition Opportunity |
| `POST /api/v1/opportunities` | Create Opportunity |

## other

| Route | What it does |
|---|---|
| `GET /health` | Health |

## products

| Route | What it does |
|---|---|
| `GET /api/v1/products/{part_number}` | Get Product |
| `GET /api/v1/products` | List Products |

## registry

| Route | What it does |
|---|---|
| `GET /api/v1/registry` | Get Registry |

## reports

| Route | What it does |
|---|---|
| `GET /api/v1/reports/{report_id}` | Run Report |
| `GET /api/v1/reports` | List Reports |

## review

| Route | What it does |
|---|---|
| `GET /api/v1/audit` | Audit Feed |
| `GET /api/v1/proposals/{proposal_id}` | Get Proposal |
| `GET /api/v1/proposals` | List Proposals |
| `GET /api/v1/runs/{run_id}/compare/{other_id}` | Compare |
| `GET /api/v1/runs/{run_id}/proposals` | Run Proposals |
| `GET /api/v1/runs/{run_id}` | Get Run |
| `GET /api/v1/runs` | List Runs |
| `POST /api/v1/opportunities/{opportunity_id}/request-review` | Request Review |
| `POST /api/v1/proposals/{proposal_id}/resolve` | Resolve |
| `POST /api/v1/runs` | Trigger Run |

## rubric

| Route | What it does |
|---|---|
| `GET /api/v1/rubric/draft` | Get Draft |
| `GET /api/v1/rubric/feedback` | Factor Feedback |
| `GET /api/v1/rubric/versions` | Get Versions |
| `POST /api/v1/rubric/impact` | Draft Impact |
| `POST /api/v1/rubric/publish-v1` | Publish V1 Version |
| `POST /api/v1/rubric/versions` | Publish Version |

## scenarios

| Route | What it does |
|---|---|
| `GET /api/v1/forecast-feed` | Forecast Feed |
| `POST /api/v1/scenarios/recompute` | Recompute |

## users

| Route | What it does |
|---|---|
| `DELETE /api/v1/users/{user_id}` | Anonymise User |
| `GET /api/v1/users` | List Users |
| `PATCH /api/v1/users/{user_id}` | Update User |
| `POST /api/v1/users/service` | Provision Service Account |
| `POST /api/v1/users` | Provision |

## webhooks

| Route | What it does |
|---|---|
| `DELETE /api/v1/webhooks/{subscription_id}` | Unsubscribe |
| `GET /api/v1/exports/audit.csv` | Export Audit |
| `GET /api/v1/exports/opportunities.csv` | Export Opportunities |
| `GET /api/v1/exports/roi-feed.json` | Export Roi Feed |
| `GET /api/v1/webhooks/deliveries` | Deliveries |
| `GET /api/v1/webhooks/events` | List Events |
| `GET /api/v1/webhooks` | List Subscriptions |
| `POST /api/v1/exports/roi-cross-check` | Roi Cross Check |
| `POST /api/v1/webhooks/retry` | Retry |
| `POST /api/v1/webhooks` | Subscribe |

## MCP tools (read-only, `python -m app.mcp.server`)

| Tool | Description |
|---|---|
| `get_rollup` | Weighted and unweighted pipeline revenue grouped by region, stage, customer or part, computed by the deterministic calc engine. Use this for any total. |
| `get_pipeline` | The opportunity rows themselves with their computed revenue, confidence, owner, rationale and evidence. Use when the answer needs specific rows. |
| `get_opportunity` | One opportunity by id or project name, with its computed figures and whether it has an open proposal. |
| `get_proposal` | A confidence proposal with its stored factors, each factor's rationale, and which guard rejected or clipped it. Quote these verbatim; do not re-derive them. |
| `get_audit_events` | The append-only confidence_event stream: proposals, approvals, overrides and rejections, with actor, role and reason code. |
| `compute_scenario` | Recompute weighted pipeline under hypothetical confidences. Nothing is written. Set include_pending_proposals to answer 'what if I approve the queue'. |
| `list_findings` | Validation findings recorded against imported snapshots. |
| `get_win_rate` | Win rate computed from the state_history event stream. |
| `get_review_queue` | Proposals currently waiting for a reviewer, in the caller's region scope. |

Scope for the MCP server comes from `OPPTRACK_MCP_USER`, `OPPTRACK_MCP_ROLE` (default `finance`) and `OPPTRACK_MCP_REGIONS` (default `*`). There is no write tool.
