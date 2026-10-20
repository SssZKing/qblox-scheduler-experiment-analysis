"""Every ported schedule builder compiles to the same schedule as qqea did.

Runs ``tools/compare_schedules.py`` case by case against the reference in
``tests/schedules/reference/`` (see its README).
"""

import importlib.util
import json
from pathlib import Path

import pytest

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "compare_schedules.py"
_spec = importlib.util.spec_from_file_location("compare_schedules", _TOOL)
compare_schedules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_schedules)

with open(compare_schedules.REFERENCE) as f:
    REFERENCE = json.load(f)

CASES = [case[0] for case in compare_schedules.cases()]


def test_every_reference_case_is_covered():
    assert sorted(CASES) == sorted(REFERENCE)


@pytest.mark.parametrize("name", CASES)
def test_schedule_matches_qqea(name):
    if name in compare_schedules.PENDING:
        pytest.skip(compare_schedules.PENDING[name])
    new = compare_schedules.dump([name])
    # dump() matches by substring; keep only this case
    new = {name: new[name]}
    report, counts = compare_schedules.compare(REFERENCE, new, verbose=True)
    assert counts["same"] == 1, report
