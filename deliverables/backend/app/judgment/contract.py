"""
ConfidenceProposal -- the model's only output (WBS 7.4).

The bounds are asserted at construction, so an out-of-bounds proposal cannot
exist as an object, let alone reach a reviewer:

- every factor that fired cites a rule ID from Matrix B and carries a non-empty
  evidence quote;
- a factor's adjustment is within its effective cap, with the correct sign;
- total movement is within the per-run cap;
- the proposed confidence sits inside [floor, ceiling];
- a proposal with movement and no fired factor is refused (no unexplained
  change).

Construction happens after the reply guards have run (app/judgment/reply_guards.py)
-- the guards decide what to keep, clip or reject and say why; the contract then
refuses to be built from anything the guards let slip. Belt and braces, on
purpose: the guards produce a reviewer-readable trace, the contract is the last
word.

This object writes nothing. Persisting it is app/services/proposals.py's job,
and applying it is a person's.
"""

from dataclasses import dataclass, field

from app.judgment.matrix_b import BY_KEY, HAIRCUT, SUPPORT, effective_cap_pp


class ContractViolation(ValueError):
    """Raised at construction. Never caught into a silent no-op: the caller
    records the failure and raises no proposal for the row."""


@dataclass(frozen=True)
class Factor:
    rule_id: str
    key: str
    delta_pp: float
    quote: str
    rationale: str
    model_confidence: float = 0.0


@dataclass(frozen=True)
class ConfidenceProposal:
    opportunity_id: str
    prior: float
    proposed: float
    factors: tuple[Factor, ...]
    rubric_version: str
    floor: float = 0.05
    ceiling: float = 0.95
    run_cap_pp: float = 20.0
    # Published per-factor caps (key -> pp); a missing key falls back to Matrix B.
    factor_caps_pp: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.floor < self.ceiling <= 1.0:
            raise ContractViolation(f"floor/ceiling {self.floor}/{self.ceiling} are not a valid band")
        if not self.floor <= self.proposed <= self.ceiling:
            raise ContractViolation(
                f"proposed confidence {self.proposed:.3f} is outside [{self.floor}, {self.ceiling}]"
            )
        movement_pp = abs(self.proposed - self.prior) * 100.0
        if movement_pp > self.run_cap_pp + 1e-9:
            raise ContractViolation(
                f"movement of {movement_pp:.1f}pp exceeds the per-run cap of {self.run_cap_pp:g}pp"
            )
        if movement_pp > 1e-9 and not self.factors:
            raise ContractViolation("a proposal that moves confidence must cite at least one factor")

        seen: set[str] = set()
        for f in self.factors:
            rule = BY_KEY.get(f.key)
            if rule is None or rule.id != f.rule_id:
                raise ContractViolation(f"factor {f.key!r} does not cite a Matrix B rule id ({f.rule_id!r})")
            if f.key in seen:
                raise ContractViolation(f"factor {f.key!r} cited twice")
            seen.add(f.key)
            if not f.quote.strip():
                raise ContractViolation(f"{rule.id} fired without an evidence quote")
            if f.delta_pp == 0.0:
                raise ContractViolation(f"{rule.id} fired with a zero adjustment")
            if rule.direction == HAIRCUT and f.delta_pp > 0:
                raise ContractViolation(f"{rule.id} is a haircut rule but proposes {f.delta_pp:+.1f}pp")
            if rule.direction == SUPPORT and f.delta_pp < 0:
                raise ContractViolation(f"{rule.id} is a support rule but proposes {f.delta_pp:+.1f}pp")
            cap = effective_cap_pp(rule, self.factor_caps_pp.get(f.key))
            if abs(f.delta_pp) > cap + 1e-9:
                raise ContractViolation(f"{rule.id} proposes {f.delta_pp:+.1f}pp against a cap of {cap:g}pp")

    @property
    def movement_pp(self) -> float:
        return (self.proposed - self.prior) * 100.0

    @property
    def fired_rule_ids(self) -> tuple[str, ...]:
        return tuple(f.rule_id for f in self.factors)
