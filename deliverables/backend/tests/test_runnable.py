"""
Regression tests for registry-driven runnable() (WBS 2.5), against the real
PARAMS registry. No real analyses or rubric factors exist yet (packages 6.0/7.0
are still To do), so these exercise the mechanism with representative
requirement sets -- exactly what a future analysis or factor would declare.
"""

import pytest

from app.analysis.registry import Analysis, AnalysisContext, AnalysisResult, available_for, register, run_all
from app.registry.parameters import PARAMS
from app.registry.runnable import run_report, runnable


def test_runnable_true_when_all_params_present():
    result = runnable("stage_mix", {"V1", "V8", "V9"}, PARAMS)  # Region, Design Status, Stage -- all present
    assert result.runnable is True
    assert result.missing == ()


def test_runnable_false_and_names_missing_param():
    result = runnable("loss_report", {"V1", "V25"}, PARAMS)  # V25 = Loss Reason Code, proposed/absent
    assert result.runnable is False
    assert result.missing == ("V25",)


def test_runnable_raises_on_unregistered_id():
    """An id the registry has never heard of is a programming error, not a dark
    input -- it must raise, not silently report as missing."""
    with pytest.raises(KeyError):
        runnable("bogus", {"V999"}, PARAMS)


def test_run_report_shape():
    modules = {
        "stage_mix": {"V1", "V9"},
        "loss_report": {"V25"},
        "channel_margin": {"V13", "V14"},
    }
    report = run_report(modules, PARAMS)
    assert set(report["ran"]) == {"stage_mix", "channel_margin"}
    assert report["dark"] == [{"module": "loss_report", "missing": ["V25"]}]


def test_analysis_registry_available_for_uses_real_param_registry():
    register(Analysis(key="test_stage_mix", label="Stage mix", requires=frozenset({"V1", "V9"}),
                      run=lambda ctx: AnalysisResult("test_stage_mix", "Stage mix", "live", "ok")))
    register(Analysis(key="test_loss_report", label="Loss report", requires=frozenset({"V25"}),
                      run=lambda ctx: AnalysisResult("test_loss_report", "Loss report", "live", "ok")))

    available = {a.key for a in available_for(PARAMS)}
    assert "test_stage_mix" in available
    assert "test_loss_report" not in available


def test_analysis_registry_run_all_reports_dark_reason():
    from datetime import date

    register(Analysis(key="test_run_all_ok", label="ok", requires=frozenset({"V1"}),
                      run=lambda ctx: AnalysisResult("test_run_all_ok", "ok", "live", f"{len(ctx.financials)} rows")))
    register(Analysis(key="test_run_all_dark", label="dark", requires=frozenset({"G1"}),
                      run=lambda ctx: AnalysisResult("test_run_all_dark", "dark", "live", "never")))

    ctx = AnalysisContext(financials=[], opportunities=[], as_of=date(2026, 9, 15))
    result = run_all(ctx, PARAMS)
    assert result["ran"]["test_run_all_ok"].headline == "0 rows"
    assert result["dark"]["test_run_all_dark"].missing == ["G1"]
    assert "Regional Target" in result["dark"]["test_run_all_dark"].note

    # A dynamically available parameter (Finance entered targets) lights it up.
    ctx.available.add("G1")
    assert "test_run_all_dark" in run_all(ctx, PARAMS)["ran"]
