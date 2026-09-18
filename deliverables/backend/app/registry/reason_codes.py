"""
Reason-code vocabulary (WBS 2.6). Closed lists for loss reason, stage-exit reason
and override reason -- the labels the calibration table (WBS 9.2's win_rate, and
the eventual L5 calibration batch) needs, so outcomes are recorded as a code
rather than prose that has to be re-read by hand to aggregate.

The lists below are PROVISIONAL, not ratified: the loss and override lists are
the ones the decision register adopted on 2026-09-09
(docs/OT_Decision_Register_and_Claude_API_Purpose.md, #41 and #43) after David
Nam did not answer; the stage-exit list is ours. Enforcement -- rejecting an
out-of-list value rather than silently accepting free text -- is what WBS 2.6
actually asks this module to build; picking the final categories is a decision
for whoever owns that vocabulary, not something to invent here. Flip DRAFT to
False once a real list is agreed, per WBS 2.6's done-when: "agreed and enforced
at the API, not just offered in a dropdown."
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReasonCodeList:
    name: str
    codes: frozenset[str]
    ratified: bool  # False = draft; enforcement is real, the category list is not signed off

    def validate(self, code: str) -> bool:
        return code in self.codes


# Decision register #43 (provisional, 2026-09-09): price, technical fit,
# competitor, relationship, timing, cancellation, other. Replaces the earlier
# draft list; the old spellings are not aliased because no production row used
# them.
LOSS_REASON_CODES = ReasonCodeList(
    name="loss_reason",
    codes=frozenset({
        "price", "technical_fit", "competitor", "relationship",
        "timing", "cancellation", "other",
    }),
    ratified=False,
)

STAGE_EXIT_REASON_CODES = ReasonCodeList(
    name="stage_exit_reason",
    codes=frozenset({
        "advanced_to_next_stage", "returned_to_earlier_stage", "stalled_no_movement",
        "design_lost", "moved_to_mass_production",
    }),
    ratified=False,
)

# WBS 8.7: why a reviewer rejected a proposal, against a closed list, so a
# factor rejected repeatedly is visible on the rubric admin screen months
# before any won/lost outcome could say the same thing.
REJECTION_REASON_CODES = ReasonCodeList(
    name="rejection_reason",
    codes=frozenset({
        "factor_misfired", "evidence_stale", "magnitude_too_large", "magnitude_too_small",
        "data_error_on_row", "other",
    }),
    ratified=False,
)

OVERRIDE_REASON_CODES = ReasonCodeList(
    name="override_reason",
    codes=frozenset({
        "rubric_missed_context", "stale_precedent", "submitter_correction",
        "new_evidence_since_proposal", "other",
    }),
    ratified=False,
)
