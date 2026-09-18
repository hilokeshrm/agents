"""
Judgment layer: proposes a calibration of the Confidence Level against the
evidence bundle for one opportunity (WBS 7.1-7.3, 7.6).

The LLM never touches Sales Revenue or Adjusted Revenue math (app/calc/engine.py).
It returns, per Matrix B rule, whether the rule fires, a signed percentage-point
adjustment, a verbatim quote from the bundle and a rationale. Everything it
returns is then checked by app/judgment/reply_guards.py and built into the
ConfidenceProposal contract (app/judgment/contract.py) before a person sees it.

Two modes:

- LIVE calls Claude with the reply shape fixed by a JSON schema on the request
  (output_config.format), not by asking for JSON in the prompt. That is what
  removed the markdown-fence failure that took out all nine projects on the
  first live run. stop_reason is checked before parsing, the text block is
  picked by type (thinking blocks come first), and a failure raises -- the
  caller decides whether a run may fall back to MOCK, and records that it did.
- MOCK is a deterministic, rule-based stand-in used in tests and local dev. It
  reads the same bundle fields the live prompt is given, so the two cannot
  disagree about what the rubric says: Matrix A is a flag on the bundle, the
  stage order is a constant, concentration is a share the caller computed.

The rules themselves live in app/judgment/matrix_b.py. RUBRIC below is that
table in the list-of-dicts shape the published rubric version stores.
"""

import json
import re

from app.core.config import settings
from app.judgment.matrix_b import (
    EARLY_OPTIMISM_TOLERANCE,
    OEM_SHARE_OF_PORTFOLIO_TRIGGER,
    ROW_SHARE_OF_REGION_TRIGGER,
    RULES,
    STAGE_ORDER,
    STALL_MULTIPLE,
    is_early,
)

PROMPT_VERSION = "2026.09-matrixB"

RUBRIC: list[dict] = [
    {
        "rule_id": r.id, "key": r.key, "label": r.label, "guidance": r.guidance,
        "direction": r.direction, "cap_pp": r.cap_pp, "requires": list(r.requires),
        "availability": r.availability,
    }
    for r in RULES
]

# Bundle fields the model is told about. Underscore fields are derived context;
# none is a currency figure (see app/services/proposals.py, EVIDENCE_FIELDS).
CITABLE_ORDER = (
    "project", "region", "customer", "end_customer", "product_line", "part_number",
    "design_status", "stage", "mp_date", "competitor_part", "owner", "confidence",
    "confidence_rationale", "evidence",
    "matrix_a_baseline", "matrix_a_forbidden", "_portfolio", "_missing_required",
    "_set_volume_ksets", "_channel_margin_pct", "_overdue_milestones",
    "_days_in_stage", "_stage_median_days", "_sop_slip_months", "_calibration", "_precedents",
)


def citable_text(bundle: dict) -> str:
    """The evidence exactly as the model sees it, one `field: value` line per
    field. A quote is verbatim when it is a substring of this text -- the same
    renderer serves the prompt and the citation guard, so 'verbatim' means one
    thing."""
    lines = []
    for key in CITABLE_ORDER:
        if key not in bundle:
            continue
        value = bundle[key]
        if value is None:
            rendered = "null"
        elif isinstance(value, (dict, list)):
            rendered = json.dumps(value, sort_keys=True, default=str)
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    return "\n".join(lines)


def _fmt(v: float) -> str:
    return f"{v:.2f}"


SYSTEM_PROMPT = f"""You are the judgment layer of a semiconductor company's Opportunity Tracking agent.

You receive ONE opportunity's evidence bundle and the Matrix B rubric. Sales Revenue and Adjusted Revenue are computed separately in code and are not in the bundle; you never see or return a revenue figure. Your only output is, per rule, whether it fires and by how many percentage points the entered Confidence Level should move.

Stage order, fixed: {" < ".join(STAGE_ORDER)}. "Early" means Concept or EVT only. DVT and PVT are not early. Mass Production is a Design Status, not a stage.

Matrix A is config, not something you infer. The bundle carries `matrix_a_forbidden` (true only when the published table forbids this Design Status x Stage cell) and `matrix_a_baseline` (the agreed confidence for the cell, or null if unset). J-01 fires ONLY when matrix_a_forbidden is true. J-04 fires ONLY when the stage is early AND confidence exceeds matrix_a_baseline by more than {EARLY_OPTIMISM_TOLERANCE}.

Rules of reply:
- A rule fires only when every field it `requires` is present (not null) in the bundle AND the evidence supports it. If a required field is null, set applies=false and say which field is missing.
- Every rule that fires MUST carry `quote`: a verbatim substring copied from the bundle text exactly as written (a whole line or part of one). A rule with no quote is discarded.
- Respect each rule's direction (haircut = negative pp, support = positive pp) and cap_pp. Do not invent risk.
- Do not fire the same rule twice. Return every rule in the rubric, fired or not."""


REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "factors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule_id": {"type": "string"},
                    "key": {"type": "string"},
                    "applies": {"type": "boolean"},
                    "confidence_adjustment_pct": {"type": "number"},
                    "quote": {"type": "string"},
                    "rationale": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["rule_id", "key", "applies", "confidence_adjustment_pct", "quote", "rationale", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["factors"],
    "additionalProperties": False,
}


def _build_user_prompt(bundle: dict) -> str:
    return (
        "MATRIX B RUBRIC (JSON):\n" + json.dumps(RUBRIC, indent=2) +
        "\n\nEVIDENCE BUNDLE (quote from these lines verbatim):\n" + citable_text(bundle)
    )


class JudgmentReplyError(RuntimeError):
    """The live path could not produce a usable reply: truncated, refused,
    unparseable or off-schema. Raised loudly; never silently mocked over."""


# --------------------------------------------------------------------------- #
# MOCK
# --------------------------------------------------------------------------- #

def _factor(rule, applies, adj, quote, rationale, conf) -> dict:
    return {
        "rule_id": rule.id, "key": rule.key, "applies": applies,
        "confidence_adjustment_pct": adj, "quote": quote, "rationale": rationale, "confidence": conf,
    }


def _silent(rule, why: str) -> dict:
    return _factor(rule, False, 0.0, "", f"{why} (MOCK scorer).", 0.3)


def _mock_score(bundle: dict) -> list:
    """Deterministic stand-in. Reads the same derived fields the prompt gives
    the model, so what fires here is what the rubric says, not a second opinion."""
    b = bundle
    stage = b.get("stage")
    status = (b.get("design_status") or "")
    confidence = b.get("confidence")
    baseline = b.get("matrix_a_baseline")
    results = []

    for rule in RULES:
        missing = [f for f in rule.requires if b.get(f) is None]
        if missing:
            results.append(_silent(rule, f"{missing[0]} is absent on this row"))
            continue

        if rule.key == "stage_status_mismatch":
            if b.get("matrix_a_forbidden") is True:
                results.append(_factor(rule, True, -20.0, "matrix_a_forbidden: True",
                    f"{status} at {stage} is a forbidden cell in the published Matrix A (MOCK scorer).", 0.7))
            else:
                results.append(_silent(rule, "matrix_a_forbidden is false; the pairing is allowed"))

        elif rule.key == "named_competitor_threat":
            part = str(b.get("competitor_part") or "").strip()
            if part and part.upper() != "TBD":
                results.append(_factor(rule, True, -10.0, f"competitor_part: {part}",
                    f"Competitor part {part} is named against this socket (MOCK scorer).", 0.6))
            else:
                results.append(_silent(rule, "no competitor part named"))

        elif rule.key == "design_win_lock_in":
            if status == "Design Win" and stage == "PVT":
                results.append(_factor(rule, True, 5.0, f"design_status: {status}",
                    "Design Win at PVT is a locked-in outcome and deserves support (MOCK scorer).", 0.6))
            else:
                results.append(_silent(rule, "not a Design Win at PVT"))

        elif rule.key == "early_stage_optimism":
            if is_early(stage) and float(confidence) > float(baseline) + EARLY_OPTIMISM_TOLERANCE:
                results.append(_factor(rule, True, -15.0, f"confidence: {confidence}",
                    f"Confidence {_fmt(float(confidence))} at {stage} exceeds the Matrix A baseline "
                    f"{_fmt(float(baseline))} by more than {EARLY_OPTIMISM_TOLERANCE} (MOCK scorer).", 0.6))
            elif not is_early(stage):
                results.append(_silent(rule, f"{stage} is not an early stage in {' < '.join(STAGE_ORDER)}"))
            else:
                results.append(_silent(rule, "confidence is within tolerance of the Matrix A baseline"))

        elif rule.key == "customer_concentration":
            p = b["_portfolio"]
            row_share = p.get("row_share_of_region")
            oem_share = p.get("end_customer_share_of_portfolio")
            if row_share is not None and row_share > ROW_SHARE_OF_REGION_TRIGGER:
                results.append(_factor(rule, True, -10.0, f"row_share_of_region\": {row_share}",
                    f"This row is {row_share:.1%} of {b.get('region')}'s weighted pipeline, over the "
                    f"{ROW_SHARE_OF_REGION_TRIGGER:.0%} single-row trigger (MOCK scorer).", 0.7))
            elif oem_share is not None and oem_share > OEM_SHARE_OF_PORTFOLIO_TRIGGER:
                results.append(_factor(rule, True, -8.0, f"end_customer_share_of_portfolio\": {oem_share}",
                    f"{b.get('end_customer')} is {oem_share:.1%} of the whole weighted pipeline, over the "
                    f"{OEM_SHARE_OF_PORTFOLIO_TRIGGER:.0%} trigger (MOCK scorer).", 0.6))
            else:
                results.append(_silent(rule, "no concentration threshold crossed"))

        elif rule.key == "submitter_calibration":
            cal = b["_calibration"]
            bias = float(cal.get("bias_pp") or 0.0)
            sd = float(cal.get("sd_pp") or 0.0)
            if sd and abs(bias) > sd:
                adj = -min(10.0, abs(bias)) if bias > 0 else min(10.0, abs(bias))
                results.append(_factor(rule, True, adj, f"bias_pp\": {cal.get('bias_pp')}",
                    f"Owner's historic bias is {bias:+.1f}pp, beyond one standard deviation (MOCK scorer).", 0.5))
            else:
                results.append(_silent(rule, "owner bias is within one standard deviation"))

        elif rule.key == "dual_sourcing":
            text = str(b.get("evidence") or "")
            m = re.search(r"(dual[- ]?sourc\w*|second source)", text, re.I)
            if m:
                results.append(_factor(rule, True, -7.0, m.group(0),
                    "The evidence names a second source for this socket (MOCK scorer).", 0.6))
            else:
                results.append(_silent(rule, "no dual-sourcing signal in the evidence"))

        elif rule.key == "cancellation_risk":
            slip = float(b.get("_sop_slip_months") or 0.0)
            text = str(b.get("evidence") or "")
            m = re.search(r"(cancel\w*|on hold|shelved)", text, re.I)
            if m:
                results.append(_factor(rule, True, -12.0, m.group(0),
                    "The evidence carries a programme cancellation signal (MOCK scorer).", 0.6))
            elif slip > 0:
                results.append(_factor(rule, True, -6.0, f"_sop_slip_months: {b.get('_sop_slip_months')}",
                    f"SoP slipped {slip:g} months since the previous snapshot (MOCK scorer).", 0.5))
            else:
                results.append(_silent(rule, "no cancellation signal and no SoP slip"))

        elif rule.key == "stage_stall":
            days, median = float(b["_days_in_stage"]), float(b["_stage_median_days"])
            if median > 0 and days > STALL_MULTIPLE * median:
                results.append(_factor(rule, True, -8.0, f"_days_in_stage: {b.get('_days_in_stage')}",
                    f"{days:.0f} days in {stage} against a median of {median:.0f} (MOCK scorer).", 0.6))
            else:
                results.append(_silent(rule, "time in stage is within the stall threshold"))

        elif rule.key == "milestone_slip":
            overdue = b["_overdue_milestones"]
            if overdue:
                first = overdue[0]
                quote = str(first.get("source_substring") or first.get("label") or "")
                results.append(_factor(rule, True, -8.0, quote,
                    f"{first.get('label')} is past due (MOCK scorer).", 0.6))
            else:
                results.append(_silent(rule, "no parsed milestone is past due"))

        elif rule.key == "eau_plausibility":
            ksets = float(b["_set_volume_ksets"])
            if ksets > 10_000:
                results.append(_factor(rule, True, -20.0, f"_set_volume_ksets: {b.get('_set_volume_ksets')}",
                    f"{ksets:,.0f} Ksets a year is implausible for one programme (MOCK scorer).", 0.7))
            else:
                results.append(_silent(rule, "set volume is plausible"))

        elif rule.key == "data_completeness":
            missing_fields = b["_missing_required"]
            if missing_fields:
                results.append(_factor(rule, True, -10.0, json.dumps(missing_fields, sort_keys=True),
                    f"Required fields missing on the row: {', '.join(missing_fields)} (MOCK scorer).", 0.8))
            else:
                results.append(_silent(rule, "every required field is present"))

        elif rule.key == "price_anomaly":
            pct = float(b["_channel_margin_pct"])  # a fraction: 0.0698 is 6.98%
            if abs(pct - 0.025) < 1e-6:
                results.append(_silent(rule, "2.5% margin is the Resale x 0.975 formula, not an anomaly"))
            elif pct < 0 or pct > 0.15:
                results.append(_factor(rule, True, -5.0, f"_channel_margin_pct: {b.get('_channel_margin_pct')}",
                    f"Channel margin of {pct:.1%} is outside the 0-15% band (MOCK scorer).", 0.6))
            else:
                results.append(_silent(rule, "channel margin is inside the observed band"))

        else:  # pragma: no cover -- every rule above is enumerated
            results.append(_silent(rule, "no mock logic for this rule"))

    return results


# --------------------------------------------------------------------------- #
# LIVE
# --------------------------------------------------------------------------- #

# Local fallback (WBS 13.3, decision #79): Western open weights only. A model
# outside these families is refused before a request is made.
ALLOWED_LOCAL_FAMILIES = ("llama", "mistral", "mixtral", "gemma", "command-r", "command r", "c4ai")
FORBIDDEN_LOCAL_FAMILIES = ("qwen", "deepseek")


def local_model_allowed(model: str) -> bool:
    m = model.lower()
    if any(f in m for f in FORBIDDEN_LOCAL_FAMILIES):
        return False
    return any(f in m for f in ALLOWED_LOCAL_FAMILIES)


def _parse_reply_text(text: str | None, blocks: list) -> list:
    if text is None:
        raise JudgmentReplyError(f"no text block in reply; block types were {blocks}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JudgmentReplyError(f"reply is not JSON despite the schema: {exc}") from exc
    factors = data.get("factors") if isinstance(data, dict) else None
    if not isinstance(factors, list):
        raise JudgmentReplyError("reply JSON has no 'factors' list")
    return factors


def _live_score_anthropic(bundle: dict) -> list:
    import anthropic  # imported lazily so the module loads fine without it installed

    from app.services.metrics import record_live_usage

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.judgment_model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(bundle)}],
        output_config={"format": {"type": "json_schema", "schema": REPLY_SCHEMA}},
    )
    usage = getattr(message, "usage", None)
    if usage is not None:
        record_live_usage(getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0,
                          model_id=settings.judgment_model)
    if message.stop_reason == "max_tokens":
        raise JudgmentReplyError("reply truncated at max_tokens before the JSON closed")
    if message.stop_reason == "refusal":
        raise JudgmentReplyError("model refused the request")
    blocks = [b.type for b in message.content]
    text = next((b.text for b in message.content if b.type == "text"), None)
    return _parse_reply_text(text, blocks)


def _live_score_vllm(bundle: dict) -> list:
    """The local path: an OpenAI-compatible vLLM endpoint on the shared RTX PRO
    6000, raw HTTP, the same JSON schema fixed on the request via
    response_format. Western open weights only."""
    import requests

    from app.services.metrics import record_live_usage

    if not local_model_allowed(settings.vllm_model):
        raise JudgmentReplyError(
            f"local model {settings.vllm_model!r} is not an approved family (Llama, Mistral, Gemma, Command R+; "
            f"never Qwen or DeepSeek -- decision #79)"
        )
    resp = requests.post(
        settings.vllm_base_url.rstrip("/") + "/chat/completions",
        json={
            "model": settings.vllm_model, "max_tokens": 8000, "temperature": 0,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": _build_user_prompt(bundle)}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "judgment_reply", "schema": REPLY_SCHEMA}},
        },
        timeout=120,
    )
    if resp.status_code != 200:
        raise JudgmentReplyError(f"vLLM returned HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    usage = data.get("usage") or {}
    record_live_usage(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)),
                      model_id=settings.vllm_model)
    choice = (data.get("choices") or [{}])[0]
    if choice.get("finish_reason") == "length":
        raise JudgmentReplyError("reply truncated at max_tokens before the JSON closed")
    text = (choice.get("message") or {}).get("content")
    return _parse_reply_text(text, ["text"] if text else [])


def _live_score(bundle: dict) -> list:
    from app.services.metrics import QuotaExceeded, check_quota

    try:
        check_quota()
    except QuotaExceeded as exc:
        raise JudgmentReplyError(str(exc)) from exc
    if settings.judgment_backend == "vllm":
        return _live_score_vllm(bundle)
    return _live_score_anthropic(bundle)


def score_confidence_factors(bundle: dict) -> dict:
    """Returns {"mode": "live"|"mock", "factors": [...], "fallback_error": str|None}.

    A live failure is not hidden: when settings.judgment_fallback_to_mock is
    true (local dev) the row is scored by MOCK and the error is returned with
    it so the run can be marked mixed; when false, the error propagates and
    the run records a failure with no proposal for the row (decision #35)."""
    live_ready = settings.anthropic_api_key if settings.judgment_backend == "anthropic" else settings.vllm_base_url
    if settings.judgment_mode == "live" and live_ready:
        try:
            return {"mode": "live", "factors": _live_score(bundle), "fallback_error": None}
        except Exception as exc:  # noqa: BLE001 -- recorded on the run, never swallowed
            if not settings.judgment_fallback_to_mock:
                raise
            print(f"[judgment/rubric.py] LIVE call failed, row scored by MOCK: {type(exc).__name__}: {exc}")
            try:
                from app.services.metrics import incr

                incr("mock_fallbacks", 1)
            except Exception:  # noqa: BLE001 -- metrics never break scoring
                pass
            return {"mode": "mock", "factors": _mock_score(bundle), "fallback_error": f"{type(exc).__name__}: {exc}"}
    return {"mode": "mock", "factors": _mock_score(bundle), "fallback_error": None}
