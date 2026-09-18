"""
Parameter registry (WBS 2.1, Layer 1). The single source of truth every other
layer declares against: rules, analyses and rubric factors cite a ParamSpec id
(`V7`), never a spreadsheet column name, so a sheet reshuffle is an intake change
and not a codebase change (docs/02-architecture/OppTrack_Complete_Architecture.html,
section 10 -- the frozen ParamSpec contract this module implements).

A proposed parameter -- one the platform needs but the current workbook does not
carry -- is registered with present_in_current_file=False rather than left out
entirely. That is what lets 2.5's runnable() report "this analysis is dark
because V25 is absent" instead of raising a KeyError somewhere downstream.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ParamSpec:
    id: str  # "V1".."V27" -- never a column name
    name: str  # "EAU"
    dtype: type  # str, float, int, bool, list -- the canonical/coerced type, not the raw cell type
    unit: str | None
    enum: tuple[str, ...] | None  # canonical values, if any; None for an open-set field
    required: bool
    tabs: tuple[str, ...]  # which TrackF (1).xlsx tabs supply it
    present_in_current_file: bool  # False = proposed, not yet a column anywhere
    note: str = ""  # provenance / caveat, kept short


class ParamRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, ParamSpec] = {}
        self._by_name: dict[str, ParamSpec] = {}

    def register(self, spec: ParamSpec) -> None:
        if spec.id in self._by_id:
            raise ValueError(f"duplicate ParamSpec id: {spec.id!r}")
        if spec.name in self._by_name:
            raise ValueError(f"duplicate ParamSpec name: {spec.name!r}")
        self._by_id[spec.id] = spec
        self._by_name[spec.name] = spec

    def get(self, param_id: str) -> ParamSpec:
        return self._by_id[param_id]

    def by_name(self, name: str) -> ParamSpec:
        return self._by_name[name]

    def all(self) -> list[ParamSpec]:
        return list(self._by_id.values())

    def by_tab(self, tab: str) -> list[ParamSpec]:
        return [p for p in self._by_id.values() if tab in p.tabs]

    def present(self) -> list[ParamSpec]:
        return [p for p in self._by_id.values() if p.present_in_current_file]

    def proposed(self) -> list[ParamSpec]:
        """Parameters the platform needs that the current workbook does not carry."""
        return [p for p in self._by_id.values() if not p.present_in_current_file]

    def __contains__(self, param_id: str) -> bool:
        return param_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)
