from datetime import date

import pytest

from app.calc.phasing import RAMP_PROFILE, mp_date_ramp


def test_mp_date_ramp_rolls_across_year_boundary():
    assert mp_date_ramp(date(2026, 12, 1)) == [
        (2026, 4, 0.10), (2027, 1, 0.20), (2027, 2, 0.30), (2027, 3, 0.40)
    ]
    assert sum(RAMP_PROFILE) == pytest.approx(1.0)