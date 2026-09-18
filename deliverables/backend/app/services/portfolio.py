"""
Portfolio context for the judgment layer (WBS 7.1) and the C12 concentration
shares (WBS 5.3).

Under the original one-row signature the concentration factor could never fire:
a single row has nothing to compare itself against. This module computes, over
the scorable rows of a run, the shares the specification's C12 names -- row
share of its region's weighted pipeline, end-customer share of the whole
portfolio, customer share, part share -- and hands each row its own slice.

Shares are ratios of C2 (Adjusted Revenue) computed by app/calc/engine.py. The
share is what reaches the model; the revenue figures behind it do not. A ratio
of two currency figures is not a currency figure, and it is the only thing J-05
needs.
"""

from dataclasses import dataclass

from app.calc.engine import ProjectFinancials


@dataclass(frozen=True)
class PortfolioShares:
    row_share_of_region: float | None
    row_share_of_portfolio: float | None
    end_customer_share_of_portfolio: float | None
    customer_share_of_portfolio: float | None
    part_share_of_portfolio: float | None
    region_row_count: int
    portfolio_row_count: int

    def as_bundle(self) -> dict:
        return {
            "row_share_of_region": _r(self.row_share_of_region),
            "row_share_of_portfolio": _r(self.row_share_of_portfolio),
            "end_customer_share_of_portfolio": _r(self.end_customer_share_of_portfolio),
            "customer_share_of_portfolio": _r(self.customer_share_of_portfolio),
            "part_share_of_portfolio": _r(self.part_share_of_portfolio),
            "region_row_count": self.region_row_count,
            "portfolio_row_count": self.portfolio_row_count,
        }


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 4)


def _share(part: float, whole: float) -> float | None:
    return None if whole <= 0 else part / whole


def concentration(financials: list[ProjectFinancials]) -> dict:
    """C12 -- concentration share by every dimension at once. Returns the
    largest single value per cut, as the specification's table shows it."""
    total = sum(f.adjusted_revenue_k for f in financials)
    cuts: dict[str, dict[str, float]] = {"region": {}, "end_customer": {}, "customer": {}, "part_number": {}, "row": {}}
    for f in financials:
        cuts["region"][f.region] = cuts["region"].get(f.region, 0.0) + f.adjusted_revenue_k
        oem = f.end_customer or "Unspecified"
        cuts["end_customer"][oem] = cuts["end_customer"].get(oem, 0.0) + f.adjusted_revenue_k
        cuts["customer"][f.customer] = cuts["customer"].get(f.customer, 0.0) + f.adjusted_revenue_k
        cuts["part_number"][f.part_number] = cuts["part_number"].get(f.part_number, 0.0) + f.adjusted_revenue_k
        cuts["row"][f.project] = f.adjusted_revenue_k
    out = {"total_adjusted_revenue_k": total, "cuts": {}}
    for cut, values in cuts.items():
        if not values:
            continue
        largest = max(values, key=values.get)
        out["cuts"][cut] = {
            "largest": largest,
            "adjusted_revenue_k": values[largest],
            "share": _share(values[largest], total),
            "shares": {k: _share(v, total) for k, v in values.items()},
        }
    return out


def portfolio_context(financials: list[ProjectFinancials]) -> dict[str, PortfolioShares]:
    """One PortfolioShares per project name, over the rows given. The caller
    decides which rows form the portfolio (a run passes its scorable set)."""
    total = sum(f.adjusted_revenue_k for f in financials)
    by_region: dict[str, float] = {}
    by_oem: dict[str, float] = {}
    by_customer: dict[str, float] = {}
    by_part: dict[str, float] = {}
    region_count: dict[str, int] = {}
    for f in financials:
        by_region[f.region] = by_region.get(f.region, 0.0) + f.adjusted_revenue_k
        region_count[f.region] = region_count.get(f.region, 0) + 1
        oem = f.end_customer or "Unspecified"
        by_oem[oem] = by_oem.get(oem, 0.0) + f.adjusted_revenue_k
        by_customer[f.customer] = by_customer.get(f.customer, 0.0) + f.adjusted_revenue_k
        by_part[f.part_number] = by_part.get(f.part_number, 0.0) + f.adjusted_revenue_k

    context: dict[str, PortfolioShares] = {}
    for f in financials:
        oem = f.end_customer or "Unspecified"
        context[f.project] = PortfolioShares(
            row_share_of_region=_share(f.adjusted_revenue_k, by_region[f.region]),
            row_share_of_portfolio=_share(f.adjusted_revenue_k, total),
            end_customer_share_of_portfolio=_share(by_oem[oem], total),
            customer_share_of_portfolio=_share(by_customer[f.customer], total),
            part_share_of_portfolio=_share(by_part[f.part_number], total),
            region_row_count=region_count[f.region],
            portfolio_row_count=len(financials),
        )
    return context
