"""Every ported schedule builder compiles to the same schedule as qqea did.

Runs ``tools/compare_schedules.py`` case by case against the references in
``tests/schedules/reference/`` (see its README): once with the mock device, once with the
lab device (``configs/quantum_device.json``) against qqea built from the snapshot it was
converted from. ``tools/compare_hardware.py`` then compares the cluster instructions.
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
_REF_DIR = Path(compare_schedules.REFERENCE).parent
with open(_REF_DIR / "qqea-4de2850-lab.json") as f:
    LAB_REFERENCE = json.load(f)
LAB_DEVICE = str(Path(compare_schedules.REPO) / "configs" / "quantum_device.json")

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


@pytest.mark.parametrize("name", CASES)
def test_schedule_matches_qqea_with_lab_device(name):
    if name in compare_schedules.PENDING:
        pytest.skip(compare_schedules.PENDING[name])
    new = {name: compare_schedules.dump([name], LAB_DEVICE)[name]}
    report, counts = compare_schedules.compare(LAB_REFERENCE, new, verbose=True)
    assert counts["same"] == 1, report


def test_cluster_instructions_match_qqea(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "compare_hardware", _TOOL.parent / "compare_hardware.py"
    )
    compare_hardware = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compare_hardware)
    monkeypatch.chdir(tmp_path)  # the Q1ASM assembler writes scratch files to the cwd
    with open(compare_hardware.REFERENCE) as f:
        reference = json.load(f)
    report, counts = compare_hardware.compare(reference, compare_hardware.dump_qsea([]))
    assert counts["different"] == 0 and counts["error"] == 0, report
