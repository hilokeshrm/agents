"""
Regression tests for the reason-code vocabulary (WBS 2.6): the lists are draft/
unratified, but enforcement -- rejecting an out-of-list value -- is real.
"""

from app.registry.reason_codes import LOSS_REASON_CODES, OVERRIDE_REASON_CODES, STAGE_EXIT_REASON_CODES


def test_lists_are_marked_draft():
    assert LOSS_REASON_CODES.ratified is False
    assert STAGE_EXIT_REASON_CODES.ratified is False
    assert OVERRIDE_REASON_CODES.ratified is False


def test_validate_accepts_known_code():
    assert LOSS_REASON_CODES.validate("price") is True
    assert STAGE_EXIT_REASON_CODES.validate("stalled_no_movement") is True


def test_validate_rejects_unknown_code():
    assert LOSS_REASON_CODES.validate("because reasons") is False
    assert OVERRIDE_REASON_CODES.validate("") is False
