# Rollout and training

How the platform goes from this repository to the sales teams, in the order the dependencies allow. Each step names what has to be true before the next one starts.

## Before anything reaches a user

1. **Security sign-off on hosted model use** (decision #76). Until it exists, `JUDGMENT_MODE=mock`: the judgment layer runs the rule-based scorer, which reads the same Matrix A and produces the same shape of proposal. Nothing else waits on this. If the answer is no, set `JUDGMENT_BACKEND=vllm` and point at the shared RTX PRO 6000 (Western weights only; the platform refuses anything else).
2. **Provision the first admin.** One row in `app_user` with role `admin` and the IdP subject, inserted by the operator. Everything after that is done from the Users screen.
3. **Configure SSO.** `AUTH_ISSUER`, `AUTH_AUDIENCE`, and either the issuer's JWKS or `AUTH_HS256_SECRET` for a dev issuer. With `AUTH_ISSUER` set, the header stand-in is off and every request needs a token or an API key.
4. **Publish rubric v1.** Rubric screen → *Publish v1 from the decision register*, or `POST /rubric/publish-v1`. Every proposal afterwards cites it.
5. **Backfill.** `python -m scripts.backfill_real_data` (the nine complete ProjectTrack rows), then `python -m scripts.backfill_ids` (sequential ids, crosswalk printed). Ask David whether the monthly TrackF files from the past year still exist: they are the only place historical state lives, and the calibration model needs two quarters of it.

## Week 1 — read only

Sales owners see their region, nothing writes. Show them the Findings screen against the workbook: the company total that does not compute, the seven TBDs, the five skeleton rows, the row implying a third of world car production. That is the argument for the field discipline in step 2.

Training: *getting-started-sales-owners.md*, thirty minutes, one region at a time. The three new habits: a rationale for every confidence, the competitor part on the row, Unit/Set filled in.

## Week 2 — intake and lifecycle

Owners enter new opportunities through the form and move existing ones on the Stage board. Every loss gets a reason code from now on. Managers get *reviewer-handbook.md* and the Review queue with the first monthly run's proposals.

Run the nightly sweep and the dispatch job from the scheduler (`python -m scripts.scheduler`, or the crontab from `python -m scripts.run_job --crontab`). Notices start arriving.

## Week 3 — the queue as the routine

The monthly run, the event runs on every stage change, and the reviewer routine: approve, override, reject with reasons. Watch `GET /rubric/feedback` — a factor rejected more than half the time it fires is a rubric change, published as a new version, not a code change.

Turn on the CRM connector in dry-run mode. Two weeks of "what would have changed" before it writes.

## Month 2 — connectors write, Finance joins

- CRM sync live; reconciliation queue handled alongside proposals.
- Finance enters targets (Analyses → Targets). Coverage lights up.
- ERP extract and the distributor POS report scheduled as drops. Forecast accuracy lights up as quarters close.
- The ROI Agent pulls `GET /exports/roi-feed.json` and posts its own figures to `POST /exports/roi-cross-check`; differences are review findings.

## Quarter 2 — learning

After two quarters of resolved outcomes, `calibration_rebuild` produces reliable owner and region bias, and J-06 starts firing. The vehicle-programme licence, if bought, drops into `market_data` and turns on the EAU cross-check and white-space detection with no other change.

## Who is trained on what

| Role | Reads | Session |
|---|---|---|
| Sales owner | getting-started-sales-owners.md | 30 min, per region |
| Manager / director | reviewer-handbook.md | 45 min, with the live queue |
| Finance | architecture-and-audit-pack.md §Reproducing a figure; connector-guide.md (ERP/POS) | 45 min |
| Admin / ops | connector-guide.md, generated/api-and-mcp-reference.md, docker-compose.yml, the scheduler | 60 min |

## What to measure

Proposals per run and the share approved unchanged; rejection rate per factor; time from proposal to decision; stalls raised and cleared; reconciliation items per connector pull; live-call cost against the monthly budget (`/metrics`). The first month's numbers are the baseline the rubric is tuned against.
