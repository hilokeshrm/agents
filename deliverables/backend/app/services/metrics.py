"""
Run observability and cost accounting (WBS 13.4, 13.6).

Counters live in Redis (fakeredis locally) under one hash per calendar month,
so the month's spend is a sum, not a scan. Every live model call records its
token usage; every run records its mode, its failures and how many rows fell
back to MOCK. `/metrics` renders them as JSON and in Prometheus text format.

Quota (decision-register section 5, WBS 13.6): when `monthly_budget_usd` is
set, a live call that would cross it is refused before it is made and the
row is scored by MOCK with the refusal recorded on the run -- the same loud
fallback a model failure gets, never a silent one.
"""

from datetime import datetime, timezone

from app.core.config import settings
from app.core.redis_client import get_redis_client as get_redis

PREFIX = "opptrack:metrics"


def _month(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def _key(now: datetime | None = None) -> str:
    return f"{PREFIX}:{_month(now)}"


def incr(field: str, amount: float = 1, *, now: datetime | None = None) -> None:
    r = get_redis()
    if float(amount).is_integer():
        r.hincrby(_key(now), field, int(amount))
    else:
        r.hincrbyfloat(_key(now), field, float(amount))


def record_live_usage(input_tokens: int, output_tokens: int, *, model_id: str, now: datetime | None = None) -> float:
    """Returns the estimated cost of this call in USD and adds it to the month."""
    cost = (input_tokens * settings.live_price_input_per_mtok + output_tokens * settings.live_price_output_per_mtok) / 1_000_000
    incr("live_calls", 1, now=now)
    incr("input_tokens", input_tokens, now=now)
    incr("output_tokens", output_tokens, now=now)
    incr("estimated_cost_usd", round(cost, 6), now=now)
    incr(f"model:{model_id}", 1, now=now)
    return cost


def month_snapshot(now: datetime | None = None) -> dict:
    raw = get_redis().hgetall(_key(now))
    out = {}
    for k, v in raw.items():
        key = k.decode() if isinstance(k, bytes) else k
        val = v.decode() if isinstance(v, bytes) else v
        try:
            out[key] = float(val) if "." in str(val) else int(val)
        except ValueError:
            out[key] = val
    out.setdefault("live_calls", 0)
    out.setdefault("estimated_cost_usd", 0.0)
    out.setdefault("runs", 0)
    out.setdefault("run_failures", 0)
    out.setdefault("mock_fallbacks", 0)
    out.setdefault("quota_refusals", 0)
    out["month"] = _month(now)
    out["monthly_budget_usd"] = settings.monthly_budget_usd
    out["budget_remaining_usd"] = (settings.monthly_budget_usd - out["estimated_cost_usd"]) if settings.monthly_budget_usd else None
    return out


class QuotaExceeded(RuntimeError):
    pass


def check_quota(*, now: datetime | None = None) -> None:
    """Raises QuotaExceeded when the month's estimated spend has reached the
    budget. A budget of 0 means no cap."""
    if not settings.monthly_budget_usd:
        return
    spent = month_snapshot(now)["estimated_cost_usd"]
    if spent >= settings.monthly_budget_usd:
        incr("quota_refusals", 1, now=now)
        raise QuotaExceeded(f"monthly budget of ${settings.monthly_budget_usd:.2f} reached (${spent:.2f} spent)")


def prometheus_text(now: datetime | None = None) -> str:
    snap = month_snapshot(now)
    lines = []
    for key, value in snap.items():
        if isinstance(value, (int, float)) and value is not None and not key.startswith("model:"):
            name = f"opptrack_{key}"
            lines.append(f"# TYPE {name} gauge")
            lines.append(f'{name}{{month="{snap["month"]}"}} {value}')
    for key, value in snap.items():
        if key.startswith("model:"):
            lines.append(f'opptrack_live_calls_by_model{{model="{key[6:]}",month="{snap["month"]}"}} {value}')
    return "\n".join(lines) + "\n"
