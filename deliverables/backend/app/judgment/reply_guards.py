"""
Guards on the model's reply -- step 6 of the ten-step run
(docs/02-architecture/OppTrack_Layer_Diagrams.html, Plate 2: "Check";
docs/02-architecture/OppTrack_Complete_Architecture.html, section 08).

The judgment layer returns percentage points, a quote and a rationale per rule.
Nothing it returns is trusted on arrival: every factor is checked here before
step 7 recomputes revenue, and a factor that fails is *rejected and shown*, not
dropped. A reviewer who only ever sees what the model got right has no way to
calibrate how much to trust the next proposal, so `check_factors` returns the
rejected ones with the guard that caught them.

Requires, direction and caps come from Matrix B (app/judgment/matrix_b.py) --
one table, cited by rule ID, not three dicts maintained by hand.

Ten guards. Two are deterministic re-checks of the rubric's own conditions,
added after the first live run (build spec, section 06, "The two misfires,
priced"):

- MATRIX_A_CONTRADICTION: J-01 fired on a pairing the published Matrix A allows.
  The bundle says `matrix_a_forbidden: False`; the model said mismatch anyway.
  Rejected. This is Aphrodite.
- NOT_EARLY: J-04 fired on a row whose stage is not Concept or EVT. Rejected.
  This is Montana.

Neither depends on the prompt being read correctly, which is the point.

The cap guard clips rather than rejects, and says so: the specification's
example is a factor returning -14pp against a cap of 10, clipped and flagged.
The per-rule cap is Matrix B's unless the published version sets a lower one.
"""

from dataclasses import dataclass, field

from app.judgment.matrix_b import BY_KEY, EITHER, HAIRCUT, SUPPORT, effective_cap_pp, is_early

# Legacy views of the rule table, kept for callers that read them by name.
FACTOR_REQUIRES: dict[str, tuple[str, ...]] = {r.key: r.requires for r in BY_KEY.values()}
FACTOR_DIRECTION: dict[str, str] = {r.key: r.direction for r in BY_KEY.values()}

# The system prompt states this range to the model; a reply outside it is a
# contract violation, not a strong opinion.
ADJUSTMENT_MIN_PP = -50.0
ADJUSTMENT_MAX_PP = 20.0

MIN_RATIONALE_CHARS = 20

GUARD_IDS = (
    "schema",
    "unknown_rule",
    "not_assessable",
    "missing_citation",
    "matrix_a_contradiction",
    "not_early",
    "wrong_direction",
    "out_of_range",
    "no_op_adjustment",
    "over_factor_cap",
)


@dataclass
class CheckedFactor:
    key: str
    applies: bool
    confidence_adjustment_pct: float
    rationale: str
    confidence: float
    accepted: bool
    rule_id: str | None = None
    quote: str = ""
    guard: str | None = None       # which guard rejected or clipped it
    detail: str | None = None
    clipped_from: float | None = None


@dataclass
class ReplyCheck:
    factors: list[CheckedFactor] = field(default_factory=list)

    @property
    def fired(self) -> list[CheckedFactor]:
        return [f for f in self.factors if f.accepted and f.applies]

    @property
    def rejected(self) -> list[CheckedFactor]:
        """Factors a guard threw out. Deliberately disjoint from not_assessable:
        a rejected factor made a claim the guards refused, an unassessable one
        never had the inputs to make a claim at all, and reporting them as one
        number would tell a reviewer the model was wrong 18 times when it was
        actually silent 18 times."""
        return [f for f in self.factors if not f.accepted and f.guard != "not_assessable"]

    @property
    def not_assessable(self) -> list[CheckedFactor]:
        return [f for f in self.factors if f.guard == "not_assessable"]

    @property
    def clipped(self) -> list[CheckedFactor]:
        return [f for f in self.factors if f.clipped_from is not None]

    @property
    def total_adjustment_pp(self) -> float:
        return sum(f.confidence_adjustment_pct for f in self.fired)


def assessable(factor_key: str, row: dict) -> tuple[bool, str | None]:
    """Whether a row carries the inputs a factor needs. Returns the first missing
    input so the reviewer sees *which* field left the factor dark."""
    for required in FACTOR_REQUIRES.get(factor_key, ()):
        if row.get(required) is None:
            return False, required
    return True, None


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def quote_is_verbatim(quote: str, citable: str | None) -> bool:
    """A quote is verbatim when it appears in the citable text the model was
    given (whitespace-normalised, case-insensitive). With no citable text
    supplied the check is skipped -- callers that have the bundle pass it."""
    if citable is None:
        return True
    q = _norm(quote)
    return bool(q) and q in _norm(citable)


def check_factors(
    raw_factors: list,
    row: dict,
    *,
    allowed_keys: set[str],
    factor_cap_pp: float | None,
    factor_caps: dict | None = None,
    citable: str | None = None,
) -> ReplyCheck:
    """Runs the guards over one reply.

    `allowed_keys` is the published rubric version's enabled factor keys -- a
    key outside it is an unknown rule, which is how a factor removed from the
    rubric stops applying to new proposals without any code change.
    `factor_cap_pp` is the version's global cap; `factor_caps` its per-factor
    caps; Matrix B's own cap applies underneath both.
    `citable` is the bundle text the model was shown; a quote must appear in it."""
    check = ReplyCheck()
    factor_caps = factor_caps or {}
    seen: set[str] = set()

    for raw in raw_factors:
        if not isinstance(raw, dict) or "key" not in raw:
            check.factors.append(CheckedFactor(
                key=str(raw)[:32], applies=False, confidence_adjustment_pct=0.0, rationale="",
                confidence=0.0, accepted=False, guard="schema",
                detail="reply item is not an object with a 'key'",
            ))
            continue

        key = str(raw.get("key"))
        applies = bool(raw.get("applies"))
        rationale = str(raw.get("rationale") or "")
        quote = str(raw.get("quote") or "")
        rule = BY_KEY.get(key)
        rule_id = rule.id if rule else raw.get("rule_id")
        try:
            adjustment = float(raw.get("confidence_adjustment_pct") or 0.0)
            confidence = float(raw.get("confidence") or 0.0)
        except (TypeError, ValueError):
            check.factors.append(CheckedFactor(
                key=key, applies=applies, confidence_adjustment_pct=0.0, rationale=rationale,
                confidence=0.0, accepted=False, guard="schema", rule_id=rule_id, quote=quote,
                detail="confidence_adjustment_pct or confidence is not a number",
            ))
            continue

        checked = CheckedFactor(
            key=key, applies=applies, confidence_adjustment_pct=adjustment,
            rationale=rationale, confidence=confidence, accepted=True, rule_id=rule_id, quote=quote,
        )

        if rule is None or key not in allowed_keys:
            checked.accepted, checked.guard = False, "unknown_rule"
            checked.detail = ("not a Matrix B rule" if rule is None
                              else "not an enabled factor in the published rubric version")
            check.factors.append(checked)
            continue

        if key in seen:
            checked.accepted, checked.guard = False, "schema"
            checked.detail = "rule cited twice in one reply"
            check.factors.append(checked)
            continue
        seen.add(key)

        ok, missing = assessable(key, row)
        if not ok:
            checked.accepted, checked.guard = False, "not_assessable"
            checked.detail = f"{missing} is absent on this row, so the factor cannot be assessed"
            checked.applies = False
            check.factors.append(checked)
            continue

        if not applies:
            # A factor that declined to fire is accepted and carries no weight;
            # it still appears in the trace, because "four factors considered and
            # did not apply" is information a reviewer uses.
            check.factors.append(checked)
            continue

        if len(rationale.strip()) < MIN_RATIONALE_CHARS or not quote_is_verbatim(quote, citable):
            checked.accepted, checked.guard = False, "missing_citation"
            checked.detail = ("fired without a rationale citing what in the context supports it"
                              if len(rationale.strip()) < MIN_RATIONALE_CHARS
                              else "quote is not a verbatim substring of the evidence bundle")
            check.factors.append(checked)
            continue

        # Deterministic re-checks of the two rules that misfired on the first
        # live run. The rubric says when they may fire; the guard says so again.
        if key == "stage_status_mismatch" and row.get("matrix_a_forbidden") is not True:
            checked.accepted, checked.guard = False, "matrix_a_contradiction"
            checked.detail = (f"{row.get('design_status')} at {row.get('stage')} is an allowed cell in the "
                              f"published Matrix A; J-01 may only fire on a forbidden cell")
            check.factors.append(checked)
            continue
        if key == "early_stage_optimism" and not is_early(row.get("stage")):
            checked.accepted, checked.guard = False, "not_early"
            checked.detail = f"{row.get('stage')} is not Concept or EVT; J-04 only applies to early stages"
            check.factors.append(checked)
            continue

        direction = rule.direction
        if (direction == HAIRCUT and adjustment > 0) or (direction == SUPPORT and adjustment < 0):
            checked.accepted, checked.guard = False, "wrong_direction"
            checked.detail = f"factor is a {direction} rule but returned {adjustment:+.1f}pp"
            check.factors.append(checked)
            continue
        assert direction in (HAIRCUT, SUPPORT, EITHER)

        if not (ADJUSTMENT_MIN_PP <= adjustment <= ADJUSTMENT_MAX_PP):
            checked.accepted, checked.guard = False, "out_of_range"
            checked.detail = f"{adjustment:+.1f}pp is outside the contract range " \
                             f"{ADJUSTMENT_MIN_PP:+.0f}..{ADJUSTMENT_MAX_PP:+.0f}pp"
            check.factors.append(checked)
            continue

        if adjustment == 0.0:
            checked.accepted, checked.guard = False, "no_op_adjustment"
            checked.detail = "fired but proposed no adjustment, which asserts a risk and prices it at zero"
            check.factors.append(checked)
            continue

        cap = effective_cap_pp(rule, factor_caps.get(key))
        if factor_cap_pp is not None:
            cap = min(cap, float(factor_cap_pp))
        if abs(adjustment) > cap:
            checked.clipped_from = adjustment
            checked.confidence_adjustment_pct = cap if adjustment > 0 else -cap
            checked.guard = "over_factor_cap"
            checked.detail = f"clipped to the cap of {cap:g}pp ({rule.id})"
            # Accepted, not rejected: the reviewer sees the model's number and
            # the applied one side by side.

        check.factors.append(checked)

    return check
