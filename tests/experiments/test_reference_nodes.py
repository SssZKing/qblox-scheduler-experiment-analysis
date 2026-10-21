"""The calibration nodes against qqea's, node by node.

Runs ``tools/compare_nodes.py`` for each node against
``tests/experiments/reference/qqea-4de2850-lab-nodes.json``: the node runs on a dummy cluster
with the lab device and simulated data, and its result, the device parameters it wrote and
the datasets it saved must match qqea's. The whole set takes about a minute.

Run in qbs_env:  python -m pytest tests/experiments/test_reference_nodes.py
"""

import importlib.util
import json
from pathlib import Path

import pytest

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "compare_nodes.py"
_spec = importlib.util.spec_from_file_location("compare_nodes", _TOOL)
compare_nodes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_nodes)

with open(compare_nodes.REFERENCE) as f:
    REFERENCE = json.load(f)

CASES = [case[0] for case in compare_nodes.CASES]


def test_every_reference_case_is_covered():
    assert sorted(CASES) == sorted(REFERENCE)


@pytest.mark.parametrize("name", CASES)
def test_node_matches_qqea(name, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # compilation writes scratch files to the working directory
    new = {name: compare_nodes.dump_qsea([name])[name]}
    report, counts = compare_nodes.compare(REFERENCE, new)
    assert counts["same"] == 1, report
