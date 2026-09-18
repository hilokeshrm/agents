# Manual test plan — Opportunity Tracking Agent

How to test the whole platform by hand, through the browser, as each role. Every
expected result below was checked against the running build on 2026-09-17
(`python -m scripts.ui_test` automates the same paths: 73 steps).

## 0. Set-up (5 minutes)

```powershell
cd deliverables\backend
alembic upgrade head                        # dev DB at migration 0010
python -m scripts.seed_demo_accounts        # five demo people, password OppTrack-2026!
cd ..
scripts\dev_up.ps1                          # backend :8000 (AUTH_MODE=local) + app :5180
```

Open **http://127.0.0.1:5180/**. To stop: `scripts\dev_down.ps1`. Logs in `logs\`.
Judgment runs in `JUDGMENT_MODE=mock` (deterministic stub, no live model) until
the security sign-off — proposals still carry rule ids, quotes and caps.

### Demo accounts (all verified, password `OppTrack-2026!`)

| Email | Role | Regions | Sees |
|---|---|---|---|
| marc@axcelai.com | Sales director | all | everything a reviewer can |
| owner-korea@axcelai.com | Sales owner | all | intake, own rows, notices, analyses — no review |
| kim@axcelai.com | Sales manager | Korea only | Korea rows and Korea proposals |
| cfo@axcelai.com | Finance | all | roll-ups, feed, targets — no intake/review |
| root@axcelai.com | Admin | — | rubric, users, connectors, access, runs — no pipeline rows |

Demo data: nine opportunities from the real workbook (Hercules, Aphrodite, Hermes,
Poseidon, Apollo, Hugo, Dresden, Yellowstone, Montana), one judgment run, nine
proposals waiting, Hermes already approved 0.30 → 0.20 in the walkthrough.

To reset the demo data at any time:
`scripts\dev_down.ps1`, then in `backend\`: delete `opptrack.db`,
`python -m scripts.walkthrough --keep-db opptrack.db`, `alembic stamp head`,
`python -m scripts.seed_demo_accounts`, then `scripts\dev_up.ps1`.

Result column: leave blank, then mark **P** / **F** with a note.

---

## A. Sign-in, sign-up and sessions

| ID | Steps | Expected | Result |
|---|---|---|---|
| A1 | Open http://127.0.0.1:5180/ signed out | Redirects to `/welcome`: landing page with **Sign in** and **Create account**; footer shows `Sign-in mode: local · code delivery: console` | |
| A2 | Create account → fill name, a new email (e.g. `you+test@example.com`), password `short` | Refused: "Use at least 10 characters" | |
| A3 | Same, password ≥ 10 chars but confirm differs | Refused: "The two passwords do not match" | |
| A4 | Same, matching password → **Create account** | "Check your email" screen. With console delivery a yellow **Development mail delivery** box shows the 6-digit code (also in `logs\backend.log`). With SMTP configured, the code arrives by email and no box is shown | |
| A5 | Enter `000000` → Verify | "wrong code; 4 attempt(s) left" (counts down each try) | |
| A6 | Enter the wrong code five times, then the right one | After the 5th wrong: "too many wrong codes; request a new one" (423). **Send a new code** issues a fresh one | |
| A7 | Press **Send a new code** twice quickly | Second press refused: "a code was sent moments ago; wait 45 seconds" | |
| A8 | Enter the correct code → Verify | Lands on `/pending`: "You're verified — waiting for a role", naming your email | |
| A9 | In another tab sign in as **root@axcelai.com** → Users → provision: user id `you`, display name, the email from A4, role `owner`, region `Korea` → **Provision person**. Back in the first tab press **Check again** | Dashboard opens as that person; sidebar profile card shows the name, **Regional sales owner**, `Regions: Korea`, "Signed in via email + password", **Sign out** | |
| A10 | **Sign out** in the profile card | Back to the landing page; browser back button does not reopen the app | |
| A11 | Sign in with `marc@axcelai.com` / a wrong password | "email or password is wrong" (same message for an unknown email — no user enumeration) | |
| A12 | Sign in with `marc@axcelai.com` / `OppTrack-2026!` | Dashboard as Sales director; **Review Queue** in the nav | |
| A13 | Press F5 | Still signed in (session in localStorage `ot-session`) | |
| A14 | Sign up again with an email that is already verified | 409 "an account with that email already exists; sign in instead" | |
| A15 | Sign in with an account that signed up but never verified | Taken to the code screen; a fresh code was issued | |
| A16 | Sign in → **Forgot your password?** → email → code → new password | "Password changed"; the old password no longer works; every other open session of that account is signed out | |
| A17 | DevTools → Application → localStorage → set `ot-session` to `junk` → F5 | Back at the landing page (401 clears the token) | |
| A18 | API check: `curl -H "X-OppTrack-Role: director" http://127.0.0.1:8000/api/v1/opportunities` | 401 "sign in first" — the dev headers are ignored in local mode | |
| A19 | Sessions expire after `AUTH_SESSION_HOURS` (12) | After expiry any click drops to the landing page | |

Gmail delivery (optional, needs your own Gmail App Password): stop the stack, set
in `backend\.env`
```
OTP_DELIVERY=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx     # Google Account > Security > 2-Step Verification > App passwords
SMTP_SENDER=you@gmail.com
```
then `scripts\dev_up.ps1` and repeat A4: the code arrives in the inbox, and the
response never contains it.

---

## B. Sales director (marc@axcelai.com)

| ID | Screen | Steps | Expected | Result |
|---|---|---|---|---|
| B1 | Dashboard | Sign in | Landing card "All regions", "9 proposal(s) waiting for you"; console pill **9 need review**; weighted projection and stretch figures; region bars | |
| B2 | Pipeline | Open | Nine rows with status pill, stage, confidence, adjusted revenue; search box filters by project/customer | |
| B3 | Intake | Fill Region `Korea`, Customer `SLM`, End customer `GM`, Project `Test-B3`, Part # `AX77`, Design status `Evaluation`, Stage `EVT`, EAU `1000`, Disty ASP `3`, Confidence `0.5`, rationale → **Add** | Toast "Created Test-B3"; row appears in Pipeline with Sales revenue $3,000K and adjusted $1,500K (= 1000 × 3 × 0.5) | |
| B4 | Intake | Design status `Mass Production`, Stage `Concept` | Refused: "design status 'Mass Production' cannot be paired with stage 'Concept' under Matrix A … (rule V-b)". (Also forbidden: Design In × EVT, Design Win × EVT) | |
| B5 | Intake | Region `Koria` | Refused: "region value 'Koria' has no canonical mapping -- not applied, not invented" | |
| B6 | Intake | Confidence `1.2` | Refused: less than or equal to 1 | |
| B7 | Intake | Design status `Lost` | A **Loss reason (required)** dropdown appears (cancellation, competitor, other, price, relationship, technical_fit, timing) with the note "entered at confidence 0.00". Submitting without a reason is refused; with one, the row is created at confidence 0 and $0 adjusted revenue | |
| B8 | Review Queue | Open, expand a proposal (**Decide**) | Card shows base → proposed confidence, weighted delta, region, owner, rubric version; expanded panel lists the rules (J-xx ids) with a verbatim quote in “quotes” and the pp cap; lifecycle proposals carry a `lifecycle` chip | |
| B9 | Review Queue | **Reject…** without choosing a reason → **Confirm reject** | Refused: "A rejection must cite a reason code" | |
| B10 | Review Queue | **Reject…** → reason `factor_misfired` → Confirm | Green "Rejected <project>"; the queue drops to 8; the console pill drops to **8 need review**; the row's confidence is unchanged | |
| B11 | Review Queue | **Approve** on a confidence proposal | "Approved <project>"; Pipeline shows the new confidence and adjusted revenue; Runs & Audit shows a confidence event by `marc` | |
| B12 | Review Queue | **Override** → value `0.55`, reason `new_evidence_since_proposal`, note | "Overrode <project>"; confidence is 0.55; audit event records override + reason | |
| B13 | Review Queue | Override with value `1.5` or no reason | "confidence must be between 0 and 1" / "an override must cite a code from the override_reason vocabulary [...]" | |
| B14 | Review Queue | Approve a **lifecycle** proposal to `Lost` without a loss reason | Refused: "Approving a Design Lost move needs the loss reason"; with a reason it succeeds and the row shows Lost | |
| B15 | Pipeline → row → Lifecycle | Move a row to `Design Win` / `PVT` | State history gains two events; moving to `Lost` demands a loss reason; `Mass Production` and `Lost` are marked "(needs approval)" | |
| B16 | Roll-ups | Open | Stretch (unweighted) vs projection (weighted) by region; company total equals the sum of regions; NRE separate | |
| B17 | Runs & Audit | Open | Runs listed with rubric version, counts and timing; the ten-step walkthrough run is present; audit feed shows confidence events, state changes, owner changes — nothing editable | |
| B18 | Import | Upload `data\TrackF (1).xlsx` → **Dry run** | Validation report: blocking and advisory findings by rule (V-a…V-i) with tab and row; nothing is written. **Commit** then writes rows and records a snapshot id | |
| B19 | Findings | Open | "Reading the workbook…" then **12 of 12** documented findings reproduced, including the `SUM(#REF!)` roll-up | |
| B20 | Analyses | Open | Cards: Stage mix, Concentration risk, Margin and price, Competitive exposure, Data quality, … each with a headline. Dark analyses (coverage, forecast accuracy, calibration, EAU cross-check) say which parameter they wait for | |
| B21 | Notices | Open | List of notifications (stalls, milestones) with delivery state; empty state text if none | |
| B22 | Ask | Type "what is the weighted pipeline by region?" → **Ask** | Answer with figures and a citation to the data it used | |
| B23 | Ask | "set Hermes confidence to 0.5" | Refuses to write and points to the Review Queue / Intake | |
| B24 | `/embed/assistant` | Open http://127.0.0.1:5180/embed/assistant | The Ask panel alone (for embedding); it answers the same questions | |

## C. Sales owner (owner-korea@axcelai.com)

| ID | Steps | Expected | Result |
|---|---|---|---|
| C1 | Sign in | Landing card for an owner; nav shows Dashboard, Pipeline, Intake, Roll-ups, Runs & Audit, Import, Analyses, Findings, Notices, Ask — **no Review Queue, Rubric, Users, Connectors, Access** | |
| C2 | Intake → create a row | Works (owners enter opportunities and their confidence at intake) | |
| C3 | Analyses | No targets form ("Save target" absent) | |
| C4 | API: approve a proposal with an owner token | 403 "role 'owner' may not 'Approve / reject proposal' (grant: no)" | |

## D. Regional manager (kim@axcelai.com, Korea)

| ID | Steps | Expected | Result |
|---|---|---|---|
| D1 | Sign in | Landing card "own region"; profile card `Regions: Korea` | |
| D2 | Pipeline | Only Korea rows (Hermes, Apollo, Poseidon, Aphrodite, Hercules …); no Dresden, Hugo, Yellowstone | |
| D3 | Review Queue | Only Korea proposals; approve/reject works on them | |
| D4 | Intake with Region `Europe` | 403 "'kim' is scoped to ['Korea']; cannot create a row in 'Europe'" | |
| D5 | Runs & Audit | No **Trigger run** button (admin only) | |

## E. Finance (cfo@axcelai.com)

| ID | Steps | Expected | Result |
|---|---|---|---|
| E1 | Sign in | Nav: Dashboard, Pipeline, Roll-ups, Runs & Audit, Analyses, Notices, Ask — no Intake, Review, Import | |
| E2 | Analyses → targets form: Region `Korea`, Period `2027`, Amount `10000` → **Save target** | "Coverage against target" lights up with "… target(s)" and the coverage ratio | |
| E3 | Roll-ups | Forecast feed available (the ROI feed contract) | |
| E4 | API: POST /opportunities as finance | 403 "role 'finance' may not 'Create / edit opportunity' (grant: no)" | |

## F. Admin (root@axcelai.com)

| ID | Screen | Steps | Expected | Result |
|---|---|---|---|---|
| F1 | Dashboard | Sign in | Nav: Dashboard, Pipeline, Roll-ups, Runs & Audit, Analyses, Notices, Ask, **Rubric, Connectors, Users, Access**; Pipeline shows no rows (admin sees configuration, not pipeline data) | |
| F2 | Rubric | Matrix A tab | Grid of Design Status × Stage with baseline confidence; forbidden cells marked; `Lost` row is 0.00 everywhere | |
| F3 | Rubric | Factors tab | 13 rules J-01…J-13, each with direction, `cap pp`, and per-factor feedback (rejections by reason) | |
| F4 | Rubric | Review policy | Control shows `gate_all`; publishing a new version requires admin and creates a new version label (old versions stay for audit) | |
| F5 | Users | Provision: user id `ui-kim`, display name, email, role `manager`, region `Korea` → **Provision person** | Row appears; provisioning `admin` with a region scope is refused ("admin has no region scope"); duplicate user id → 409 | |
| F6 | Users | Deactivate / delete a person | Row is anonymised, audit rows keep their actor id; that email's session gets 403 "account is deactivated" on every screen and `/auth/session` reports `provisioned: false` | |
| F7 | Connectors | Open | Four connectors: CRM sync (trust 3), ERP extract (4), Distributor POS (2), Vehicle programme (0) with the parameters each supplies | |
| F8 | Connectors | Choose CRM, upload a CSV `Opportunity ID,End Customer` / `OPP-000001,General Motors` → **Pull** (dry run) | Report of what *would* change: "dry run, nothing written"; gated fields (status/stage/confidence) would become reconciliation items, never direct writes | |
| F9 | Access | Open | The grant matrix (action × role) exactly as enforced, and the enforcement points list | |
| F10 | Runs & Audit | **Trigger run** | A new run appears; proposals are re-generated; **Compare two runs** shows per-row attribution of what changed and why | |
| F11 | Intake / Review | Try via API with an admin token | 403 — admin cannot create rows or decide proposals | |

## G. Cross-cutting

| ID | Steps | Expected | Result |
|---|---|---|---|
| G1 | Any audit row: try to edit/delete via API (`PATCH /confidence-events/{id}`) | 405/403 — append-only tables; no route exists | |
| G2 | Theme toggle (sun/moon) and design picker in the top bar | Dark and light both readable; choice survives reload | |
| G3 | Narrow the window to phone width | Sidebar collapses; no horizontal scroll | |
| G4 | Backend log while asking the assistant | Every conversation is logged with tools used and grounding | |
| G5 | `GET /api/v1/metrics` | Prometheus text: runs, proposals, decisions, request latency | |
| G6 | `GET /api/v1/access/me` with a session token | `identity_source`, role, regions, grants — the same copy the UI uses for its nav | |

## H. Automated equivalents

```powershell
cd deliverables\backend
pytest -q                          # 370 backend tests
python -m scripts.ui_test          # 73 browser steps (5 roles + sign-in); screenshots in ..\ui-report\
python -m scripts.findings_report  # the twelve workbook findings
```
