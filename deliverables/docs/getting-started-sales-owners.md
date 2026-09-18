# Getting started — regional sales owners

You enter and evidence opportunities. The agent proposes a confidence; your manager decides it. This replaces the TrackF spreadsheet: nothing you did in the sheet is lost, and three things you could not do in it are now expected of you.

## Signing in

There is no sign-up. An admin provisions your account against the corporate directory; you sign in with the company SSO and the platform recognises you by email the first time. If you see "not provisioned", ask an admin — nobody can grant themselves access.

You see your own region and nothing else. That is not a display setting; the database query never returns another region's rows.

## Adding an opportunity (Intake)

The form is the intake schema. Fields come in three tiers:

- **Needed to compute revenue** — region, customer, project, part number, design status, stage, EAU (Kpcs), distributor ASP, confidence. Without these the row is refused, because Sales Revenue cannot be computed from it.
- **Required** — end customer, application, product line, owner (you), and a **confidence rationale**. A row missing one of these is accepted with an advisory finding, and the data-completeness factor will haircut its confidence until you fill it.
- **Optional** — M/P date, Unit/Set, resale ASP, NRE charge, competitor part, evidence, a quarterly volume profile.

Three things the sheet never asked for and this does:

1. **A rationale for your confidence.** One sentence: why 0.65 and not 0.5. The agent argues from an agreed baseline (a Design In at DVT starts at 0.65); your rationale is what it argues against.
2. **The competitor part.** The sheet had it on Funnel and blank on ProjectTrack. Enter it here; two rubric factors (named competitor, dual sourcing) cannot fire without it.
3. **Unit/Set.** Chips per vehicle. It is not a revenue multiplier — EAU is already in chips — but it gives vehicle sets, and vehicle sets are how a 32-million-cars-a-year volume gets caught.

Design Status and Stage have to go together: Design Win only at PVT, Design In at DVT or PVT, Sample/Evaluation/Promotion at Concept or EVT. The form refuses a pairing the table forbids and says why (rule V-b).

## Moving a row

Change the stage on the Stage board or the opportunity page. Every move is a history event with you as the actor and, for a stage exit, a reason from the list. Mass Production and Design Lost need a manager: you can ask, you cannot close. A loss needs a loss reason at the moment of the loss — that is the one piece of information the sheet threw away and the calibration model needs most.

## What the agent does with your row

Once a month (and whenever a row's stage or status changes) it scores the row against thirteen rules, quoting your evidence text verbatim, and puts a proposal in your manager's queue. You can ask for a review any time from the opportunity page. You will see every proposal on your rows, with the rules that fired and what the guards refused, but you cannot approve one — nobody approves their own number.

## Notices

Stalls (a row sitting past its stage's median), overdue milestones parsed from your own evidence text ("PPAP: Oct'25"), and reconciliation questions from the CRM come to you under Notices. Fix the row, or note why it is right.

## Asking questions

"Ask OppTrack" answers from the same figures the screens show. It cannot change anything, and if it quotes a figure no tool returned, the answer is flagged. Try: *what is the weighted pipeline for Korea*, *why did Hermes get proposed at 0.20*, *what if we approve the queue*.
