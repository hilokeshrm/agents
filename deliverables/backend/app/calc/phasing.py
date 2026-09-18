"""
Quarterly phasing (WBS 5.5, C11) -- decision #65, provisional.

How one annual EAU becomes quarterly revenue, in order of preference:

1. PROGRAMME  a per-opportunity volume profile -- units per quarter, keyed by
              calendar year -- when the source data carries one (decision #66).
              FCST_Revenue's quarterly columns are exactly this for the rows
              that have them; the reader hands them over as
              `cy25_units_q1` .. `cy26_units_q4`.
2. RAMP       from the M/P date: 10 / 20 / 30 / 40 % of the annual figure over
              the M/P quarter and the next three. Fractions sum to one, so
              phasing changes timing, never total revenue.
3. UNPHASED   no profile and no M/P date: the figure is reported whole and
              labelled unphased rather than dropped or guessed into a quarter.

Every result carries its `basis`, so a feed can say how much of a quarter's
figure came from a programme profile and how much from the ramp. Pure
functions: no I/O, no clock -- `today` is an argument where it matters.
"""

from dataclasses import dataclass
from datetime import date

RAMP_PROFILE: tuple[float, ...] = (0.10, 0.20, 0.30, 0.40)
PROGRAMME, RAMP, UNPHASED = "programme", "ramp", "unphased"


@dataclass(frozen=True)
class Quarter:
    year: int
    quarter: int
    fraction: float          # share of the annual figure landing here
    units_kpcs: float | None  # absolute units when a programme profile gave them


@dataclass(frozen=True)
class Phasing:
    basis: str
    quarters: tuple[Quarter, ...]

    @property
    def fractions_sum(self) -> float:
        return sum(q.fraction for q in self.quarters)


def add_quarters(year: int, quarter: int, offset: int) -> tuple[int, int]:
    index = year * 4 + (quarter - 1) + offset
    return index // 4, index % 4 + 1


def mp_date_ramp(mp_date: date) -> list[tuple[int, int, float]]:
    quarter = (mp_date.month - 1) // 3 + 1
    return [
        (*add_quarters(mp_date.year, quarter, offset), fraction)
        for offset, fraction in enumerate(RAMP_PROFILE)
    ]


def profile_from_fields(fields: dict) -> dict[int, list[float]] | None:
    """A programme profile from reader fields shaped `cy25_units_q1` ..
    `cy26_units_q4`. Returns {2025: [q1..q4], 2026: [...]} or None when no
    quarter carries a value."""
    profile: dict[int, list[float]] = {}
    for name, value in fields.items():
        if not name.startswith("cy") or "_units_q" not in name or value is None:
            continue
        try:
            year = 2000 + int(name[2:4])
            q = int(name[-1])
            units = float(value)
        except (TypeError, ValueError):
            continue
        profile.setdefault(year, [0.0, 0.0, 0.0, 0.0])[q - 1] = units
    return profile or None


def phase(
    *,
    eau_kpcs: float,
    mp_date: date | None,
    profile: dict[int, list[float]] | None = None,
) -> Phasing:
    """The rule. `profile` wins when present and non-zero; then the M/P ramp;
    then unphased."""
    if profile:
        total_units = sum(sum(qs) for qs in profile.values())
        if total_units > 0:
            quarters = tuple(
                Quarter(year=int(year), quarter=i + 1, fraction=units / total_units, units_kpcs=units)
                for year, qs in sorted(profile.items(), key=lambda kv: int(kv[0]))
                for i, units in enumerate(qs)
                if units
            )
            return Phasing(basis=PROGRAMME, quarters=quarters)
    if mp_date is not None:
        return Phasing(
            basis=RAMP,
            quarters=tuple(
                Quarter(year=y, quarter=q, fraction=f, units_kpcs=eau_kpcs * f)
                for y, q, f in mp_date_ramp(mp_date)
            ),
        )
    return Phasing(basis=UNPHASED, quarters=())


def quarterly_revenue_k(phasing: Phasing, annual_revenue_k: float) -> dict[tuple[int, int], float]:
    """Revenue per (year, quarter) from a phasing and an annual figure --
    T2's shape: units x the same ASP in every quarter, no price erosion
    modelled (the workbook does not either; see the build spec's T2 note)."""
    return {(q.year, q.quarter): annual_revenue_k * q.fraction for q in phasing.quarters}
