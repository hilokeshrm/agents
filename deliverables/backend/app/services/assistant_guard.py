"""
Grounding, refusal and logging for the assistant (WBS 14.2, 14.4, 14.5).

Three things wrap every answer, in both modes:

GROUNDING (14.2). A currency or percentage figure in an answer must be
traceable to a tool result the answer was built from. `check_grounding` walks
the numbers in the answer text, normalises them, and looks for each in the
serialised tool outputs. A figure with no source marks the answer ungrounded;
the API returns that flag and the list of untraceable figures, and the live
prompt is told to cite the tool that produced each figure. The reader mode is
grounded by construction -- it only prints what a tool returned.

REFUSAL AND REDIRECT (14.4). Two classes of question are not answered:
a request to change something (there is no write tool, and the answer says
which screen does it) and a question outside the pipeline (people's personal
details, other companies' business, general chat). Both get a short, plain
refusal and a pointer, never a guess.

LOGGING (14.5). Every question and answer is a `conversation` row: who asked,
what mode answered, which tools ran, whether the answer was grounded, the
request id. Feeds cost and quota (13.6) and the grounding tests (12.7).
"""

import json
import re
from dataclasses import dataclass, field

_NUMBER = re.compile(r"\$?\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s?(K|M|%|pp)?", re.I)

WRITE_INTENT = re.compile(
    r"\b(set|change|update|approve|reject|override|move|close|mark|create|add|delete|remove|publish|enter|"
    r"raise|lower|bump|promote|resolve)\b.*\b(confidence|proposal|stage|status|opportunit|row|record|rubric|"
    r"matrix|user|target|design|lost|production|queue|pvt|dvt|evt|concept|won)",
    re.I,
)
OUT_OF_SCOPE = re.compile(
    r"\b(home address|phone number|salary|password|api key|secret|credit card|weather|joke|poem|recipe|"
    r"stock price|share price|politic|religion|medical|diagnos)\b", re.I,
)
PIPELINE_WORDS = re.compile(
    r"\b(pipeline|opportunit|proposal|confidence|revenue|forecast|region|customer|design|stage|status|"
    r"run|audit|rubric|finding|stall|milestone|target|coverage|margin|competitor|owner|win rate|scenario|"
    r"what if|queue|approve|hermes|korea|europe|taiwan|japan|eau|asp|part|socket|nre|actual|weighted|"
    r"concentration|proposed|rejected|why|how much|which|who|when|list|show|total|pvt|dvt|evt|concept)\b", re.I,
)

REDIRECTS = {
    "confidence": "the Review queue (approve, reject or override a proposal) or the opportunity page (request a review)",
    "proposal": "the Review queue",
    "stage": "the Stage board or the opportunity page",
    "pvt": "the Stage board or the opportunity page",
    "dvt": "the Stage board or the opportunity page",
    "evt": "the Stage board or the opportunity page",
    "concept": "the Stage board or the opportunity page",
    "status": "the opportunity page (Lifecycle controls; Mass Production and Design Lost need a manager)",
    "rubric": "Rubric & Matrix A (admin)",
    "matrix": "Rubric & Matrix A (admin)",
    "user": "Users & access (admin)",
    "target": "Roll-ups (Finance enters targets)",
    "opportunit": "the Intake form",
    "row": "the Intake form",
    "record": "the opportunity page",
}


@dataclass
class Intent:
    kind: str                 # answer | refuse_write | refuse_scope
    message: str | None = None


def classify(question: str) -> Intent:
    q = question.strip()
    if OUT_OF_SCOPE.search(q) and not PIPELINE_WORDS.search(q):
        return Intent("refuse_scope", "That is outside what I can see. I read the design-win pipeline -- "
                                      "opportunities, proposals, runs, findings, roll-ups -- and nothing else.")
    lowered = q.lower()
    is_what_if = "what if" in lowered or lowered.startswith("if ") or " if " in lowered or "would" in lowered
    if WRITE_INTENT.search(q) and not is_what_if:
        target = next((k for k in REDIRECTS if k in lowered), "record")
        return Intent("refuse_write", f"I can't make that change: there is no tool here that writes. Do it in "
                                      f"{REDIRECTS[target]}. I can tell you what it would do to the numbers "
                                      f"first -- ask me 'what if'.")
    if not PIPELINE_WORDS.search(q) and len(q.split()) > 2:
        return Intent("refuse_scope", "I can only answer questions about the pipeline. Try a region, a project "
                                      "name, the review queue, or 'what if'.")
    return Intent("answer")


@dataclass
class Grounding:
    grounded: bool
    figures: list[str] = field(default_factory=list)
    untraceable: list[str] = field(default_factory=list)


def _numbers_in(text: str) -> list[float]:
    out = []
    for whole, frac, unit in _NUMBER.findall(text):
        digits = whole.replace(",", "")
        try:
            value = float(digits + ("." + frac if frac else ""))
        except ValueError:
            continue
        out.append(value)
        if unit and unit.upper() == "K":
            out.append(value * 1000)
        if unit == "%":
            out.append(value / 100)
    return out


def _traceable(value: float, haystack: list[float], *, tolerance: float) -> bool:
    return any(abs(h - value) <= tolerance * max(1.0, abs(value)) for h in haystack)


def check_grounding(answer: str, tool_outputs: list) -> Grounding:
    """Every figure in the answer must appear, in some normalisation, in what
    the tools returned. Small integers (counts under 20) are not figures. A
    percentage matches a tool ratio to within half a point; a currency figure
    matches to within a tenth of a percent (display rounding)."""
    haystack = _numbers_in(json.dumps(tool_outputs, default=str))
    figures, untraceable = [], []
    for whole, frac, unit in _NUMBER.findall(answer):
        raw = whole + ("." + frac if frac else "") + (unit or "")
        digits = whole.replace(",", "")
        try:
            value = float(digits + ("." + frac if frac else ""))
        except ValueError:
            continue
        if value < 20 and not unit:
            continue
        figures.append(raw)
        if unit == "%":
            ok = _traceable(value / 100, haystack, tolerance=0.0) or any(abs(h - value / 100) <= 0.005 for h in haystack)
        elif unit and unit.upper() == "K":
            ok = _traceable(value, haystack, tolerance=0.001) or _traceable(value * 1000, haystack, tolerance=0.001)
        else:
            ok = _traceable(value, haystack, tolerance=0.001)
        if not ok:
            untraceable.append(raw)
    return Grounding(grounded=not untraceable, figures=figures, untraceable=untraceable)
