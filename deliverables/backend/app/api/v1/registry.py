"""
The vocabularies and canonical value sets a client needs in order to send
something the API will accept (WBS 2.2, 2.6).

This router exists to remove a class of bug rather than to add a feature. A
reason code is enforced at the API against app/registry/reason_codes.py, and a
design status is canonicalised against app/registry/enums.py -- so a screen that
hardcodes either list is one edit away from offering a value the server rejects.
Serving the lists means the dropdown and the enforcement cannot disagree.

`ratified` is reported per vocabulary and is currently false for all three: the
enforcement is real, the category lists are still draft (see that module's
docstring). A UI that shows the codes should say so rather than presenting a
draft vocabulary as settled.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.registry.enums import DESIGN_STATUS_MAP, STAGE_VALUES
from app.registry.reason_codes import (
    LOSS_REASON_CODES,
    OVERRIDE_REASON_CODES,
    REJECTION_REASON_CODES,
    STAGE_EXIT_REASON_CODES,
    ReasonCodeList,
)
from app.services.state_transitions import APPROVAL_REQUIRED_STATUSES

router = APIRouter(prefix="/registry", tags=["registry"])


class VocabularyRead(BaseModel):
    name: str
    codes: list[str]
    ratified: bool
    required_when: str | None = None


class RegistryRead(BaseModel):
    design_statuses: list[str]
    stages: list[str]
    # Design statuses a person cannot set on their own -- the lifecycle gate in
    # app/api/v1/opportunities.py reads the same constant, so a UI that labels a
    # control from this list is labelling the rule that will actually be applied.
    approval_required_statuses: list[str]
    reason_codes: dict[str, VocabularyRead]


def _vocabulary(source: ReasonCodeList, required_when: str | None = None) -> VocabularyRead:
    return VocabularyRead(
        name=source.name, codes=sorted(source.codes), ratified=source.ratified, required_when=required_when,
    )


@router.get("", response_model=RegistryRead)
def get_registry() -> RegistryRead:
    return RegistryRead(
        # dict.fromkeys de-duplicates the variant map to one entry per canonical
        # value ("m/p" and "mass production" are one status, not two).
        design_statuses=list(dict.fromkeys(DESIGN_STATUS_MAP.values())),
        stages=list(STAGE_VALUES),
        approval_required_statuses=sorted(s.title() for s in APPROVAL_REQUIRED_STATUSES),
        reason_codes={
            "loss_reason": _vocabulary(
                LOSS_REASON_CODES, required_when="design status becomes Lost",
            ),
            "stage_exit_reason": _vocabulary(
                STAGE_EXIT_REASON_CODES, required_when=None,
            ),
            "override_reason": _vocabulary(
                OVERRIDE_REASON_CODES, required_when="a reviewer overrides a proposal with their own value",
            ),
            "rejection_reason": _vocabulary(
                REJECTION_REASON_CODES, required_when="a reviewer rejects a proposal",
            ),
        },
    )
