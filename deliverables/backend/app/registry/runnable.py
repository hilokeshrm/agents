"""
Registry-driven runnable() (WBS 2.5). Answers, for any module that declares the
parameter ids it needs, whether the current snapshot can actually supply them.
This is the mechanism behind "not-assessable" behaviour throughout the platform:
an analysis (WBS 6.0) or rubric factor (WBS 7.0) whose inputs are absent reports
that it cannot run, rather than running on nulls and producing a confident number
from nothing.

Consumers don't exist yet -- package 6.0's analysis registry and 7.0's rubric
factors are still To do -- so this is exercised here against representative
requirement sets rather than real callers. The mechanism itself is complete and
tested; wiring it into an actual analysis or factor is that package's job, not
this one's.
"""

from dataclasses import dataclass

from app.registry.param_spec import ParamRegistry


@dataclass(frozen=True)
class RunnableResult:
    module: str
    runnable: bool
    missing: tuple[str, ...]  # param ids the current snapshot does not supply


def runnable(module: str, requires: set[str], registry: ParamRegistry) -> RunnableResult:
    """requires is the set of ParamSpec ids a module (an analysis, a rubric
    factor) declares it needs. A ParamSpec must both exist in the registry and be
    present_in_current_file -- an unregistered id is a programming error (raised,
    not reported as merely dark), a registered-but-proposed id is legitimately
    dark and belongs in `missing`."""
    missing = []
    for param_id in sorted(requires):
        spec = registry.get(param_id)  # raises KeyError for an unregistered id -- a bug, not a dark input
        if not spec.present_in_current_file:
            missing.append(param_id)
    return RunnableResult(module=module, runnable=not missing, missing=tuple(missing))


def run_report(modules: dict[str, set[str]], registry: ParamRegistry) -> dict[str, list]:
    """The run-output shape WBS 2.5's done-when asks for: every module reports
    runnable or not, and the dark ones say why. modules maps a module name to the
    param ids it requires."""
    ran, dark = [], []
    for name, requires in modules.items():
        result = runnable(name, requires, registry)
        if result.runnable:
            ran.append(name)
        else:
            dark.append({"module": name, "missing": list(result.missing)})
    return {"ran": ran, "dark": dark}
