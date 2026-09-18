# Reviewer handbook

For sales managers and regional directors — the people who decide what the agent proposes. Ten minutes to read; everything here is also enforced by the API, so nothing depends on you remembering it.

## What you are deciding

The agent writes exactly one field: **Confidence Level**. Every dollar figure in the pipeline is Sales Revenue (EAU × Distributor ASP) times that confidence, computed in plain code the model cannot reach. When you approve a proposal you are approving a number that a rule argued for, with a quote from the row's own evidence. When you reject it, you are telling the rubric it was wrong — and that is recorded, per factor, so a factor that keeps being rejected shows up on the rubric screen months before any lost deal could.

Three kinds of item reach your queue:

| Kind | What the agent did | What you decide |
|---|---|---|
| **Confidence proposal** | Scored a row against Matrix B and proposed a new confidence, capped and cited | Approve, override with your own value (with a reason), or reject (with a reason) |
| **Lifecycle move** | Noticed a Design Win at PVT past its M/P date, or evidence saying the socket was lost | Approve the move (Lost needs a loss reason from you) or reject it |
| **Reconciliation** | A connector (CRM, ERP) reported a value that did not out-rank what is on the row | Take the connector's value or keep the row's |

The agent never applies any of these itself. Under the v1 policy (`gate_all`) every proposal waits for a person.

## Reading a proposal

Each fired factor shows its rule id (J-01 … J-13), the points it moved, a **verbatim quote** from the row, and its rationale. Factors the guards refused are shown too, struck through with the guard that caught them — you are meant to see what the model got wrong, not only what it got right.

Things to check, in order:

1. **The quote.** Does the cited text actually support the factor? If the quote says "dual sourcing likely" and the row's evidence says the customer *rejected* dual sourcing, reject with `factor_misfired` and name J-07.
2. **The flags.** `clamped_from` means the proposal hit the 0.05 floor or 0.95 ceiling; `run_cap_clipped_from_pp` means the factors added to more than 20 points and were clipped. Both always come to you.
3. **The band.** A proposal that crosses a lifecycle band (say, from an early-stage figure past 0.65 into Design In territory) is asking you to agree the row has changed character, not just number.
4. **The money.** The queue shows what the change does to the row's weighted revenue. Concentration (J-05) fires a lot on this portfolio — Ford is 60% of the weighted pipeline — so expect it; disagree with the *magnitude*, not the fact, if the evidence supports the row.

## The four decisions

- **Approve** — the proposed confidence becomes the row's. Revenue is recomputed by the calc engine from that number; nothing is cached from the proposal.
- **Override** — your own value, with a reason from the override list (`rubric_missed_context`, `stale_precedent`, `submitter_correction`, `new_evidence_since_proposal`, `other`). Use it when the agent's direction is right and its number is wrong.
- **Reject** — the row keeps its number. A reason from the rejection list is required (`factor_misfired`, `evidence_stale`, `magnitude_too_large`, `magnitude_too_small`, `data_error_on_row`, `other`); naming the factors you disagree with is optional and worth doing.
- **Lifecycle approve** — for a move to Lost, you supply the loss reason (`price`, `technical_fit`, `competitor`, `relationship`, `timing`, `cancellation`, `other`). The agent proposes the move; you record why.

## Rules the system enforces on you

- You cannot resolve a proposal on a row you own. If you are both the owner and the region's manager, another manager or a director has to.
- A manager decides inside their region; a director across regions; Finance and admin never decide a proposal.
- Closing a record — Mass Production or Design Lost — needs the close grant (manager in region, director anywhere), whether a person or the agent started it.
- Nothing you decide can be edited afterwards. A correction is a new decision.

## When the agent is wrong

Reject with the reason, and name the factor. The rubric admin sees rejection rates per factor and can lower a cap or disable a factor by publishing a new rubric version; nothing you do in the queue changes the rubric directly. If a factor is wrong because the *row* is wrong (a stale competitor part, a missing Unit/Set), fix the row and ask for a re-review from the opportunity page.

## What you will not find

There is no button that lets the agent approve on its own, no way to edit an audit entry, and no way to see a row outside your region — not hidden, absent: the query never returns it.
