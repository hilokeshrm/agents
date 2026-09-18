# Opportunity Tracking Agent, Proof of Concept

This is Step 3 of the Opportunity Tracking Agent build plan, the same POC pattern used for the ROI Agent: prove the deterministic-math-plus-LLM-judgment split works before building anything else.

## What this proves

1. calc_engine.py reimplements TrackF_1.xlsx's ProjectTrack math (Sales Revenue = EAU times Distributor ASP, Adjusted Revenue = Sales Revenue times Confidence Level) as plain, tested Python, with zero LLM involvement. test_calc_engine.py checks it reproduces the sheet's own numbers exactly for all 9 sample pipeline projects.
2. judgment.py calibrates the human-entered Confidence Level against project context (design status versus validation stage consistency, named competitor threats, design-win lock-in, early-stage optimism), the same pattern as the ROI Agent's discount-factor scoring, returning a structured, cited adjustment rather than touching the revenue math directly.
3. run_poc.py runs the whole pipeline through both steps and shows the portfolio-level weighted revenue before and after calibration, with the specific factors that moved each project.

## Running it

```
cd opptrack_poc
python3 run_poc.py          # runs end to end, no setup required (uses a MOCK judgment layer)
python3 test_calc_engine.py # regression test against the spreadsheet's own numbers
python3 calc_engine.py      # calc engine only
python3 judgment.py         # judgment layer only, single project example
```

No dependencies beyond the Python standard library are required to run in MOCK mode.

## Going from MOCK to a live judgment layer

```
pip install anthropic
export ANTHROPIC_API_KEY=sk-...
python3 run_poc.py
```

## What is deliberately not in this POC yet

- No structured intake UI or database. Inputs are a hand-written JSON file standing in for the Funnel and ProjectTrack tabs.
- No stage-transition automation (moving a project from ProjectTrack into Mass Production or Design Lost when its stage resolves).
- No submitter reliability profiles (needs real historical won/lost outcomes to seed).
- No connection to the ROI Agent, which is meant to consume this agent's Adjusted Revenue as its own revenue-forecast input.

Those are exactly the Step 4 scale-up items.
