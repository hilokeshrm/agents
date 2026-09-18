# Connector guide

How a source other than a person gets a value onto a row, and why it can never overwrite one silently.

## The ladder (decision #63)

| Rung | Source | Trust | Wins over |
|---|---|---|---|
| 5 | Human edit / human-reconciled | `direct_entry`, `human_reconciled` | everything |
| 4 | ERP extract | `erp` | CRM, POS, import |
| 3 | CRM sync | `crm` | POS, import |
| 2 | Distributor POS / POR | `pos` | import |
| 1 | Workbook / CSV import | `import` | inferred |
| 0 | Inferred, market data | `inferred`, `market` | nothing |

Every value on a row carries the rung it came from (`field_value`, one row per parameter per observation). A connector observation is **always** recorded as provenance; whether it is **applied** depends on the rung of what is already there:

- higher rung than the current value → applied to the row;
- empty field → filled, whatever the rung (an absence has no trust to defend);
- equal or lower rung → a **reconciliation item** in the review queue; a person takes the connector's value or keeps the row's;
- design status, stage, confidence → never applied by a connector at any rung. A stale CRM stage is a question, not a write.

## The four connectors

| Name | Supplies | Cadence | Reads |
|---|---|---|---|
| `crm` | dimensions, identity (external id), declared status, M/P date, EAU, competitor, owner | nightly | the CRM's opportunity export, CSV or JSON, same header aliases as the import wizard |
| `erp` | shipped revenue, units, invoiced ASP (A1) | nightly | CSV: `part_number, customer, region, year, quarter, revenue_k, units_kpcs, invoiced_asp` |
| `disty_pos` | point-of-sale units (A2) | monthly | CSV: `part_number, customer, region, year, quarter, units_kpcs[, revenue_k, resale_asp]` |
| `market_data` | programme build volumes and SoP (P1/P2) | monthly | CSV: `programme, oem, region, application, sop, build_volume_ksets` — needs the data licence |

ERP and POS write **actuals**, not row fields; forecast accuracy (C15) compares a forecast vintage against them. ERP's invoiced ASP is also an observation against every open opportunity on that part and customer, at ERP trust.

## Running a pull

Three ways, one code path:

1. **Screen** — Connectors: choose the connector, the file, tick *dry run* first. A dry run records what would change and writes nothing; leave a new connector on dry run for a fortnight before you let it write.
2. **API** — `POST /api/v1/connectors/{name}/pull` (multipart `file`, form field `dry_run`), as the connector's service account (`X-OppTrack-Api-Key`) or an admin.
3. **Drop folder** — the `connector_sync` job pulls every file under `data/drops/<connector>/`, moves it to `done/` or `failed/`, hourly.

The result says how many observations matched a row, how many were applied, how many became reconciliation items, and how many rows it could not match. Unmatched rows are listed; they are a crosswalk problem (the CRM's id is not on the row yet), not a data problem.

## Service accounts

A connector authenticates as a service account provisioned by an admin (`POST /users/service`), scoped to one connector, with an API key shown once. By the roles matrix a service account writes provenanced field values and nothing else: it cannot enter a confidence, move a record, or act as a person.

## Live endpoints

The connectors read exports. Pointing one at a live CRM/ERP API is a credential and a fetch in front of the same `pull()`; the framework, the ladder and the queue do not change. Do not put credentials in code — they belong in the deployment's secret store and the service account.
