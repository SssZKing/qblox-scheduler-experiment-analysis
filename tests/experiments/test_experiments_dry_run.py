"""Dry run on a qblox-instruments dummy cluster: schedules compile, run and save.

Uses the lab configs in ``configs/`` and never touches the real cluster:

    python -m pytest tests/experiments/test_experiments_dry_run.py
"""

import numpy as np
import pytest
from qcodes.instrument import Instrument
from quantify_core.data.handling import load_snapshot
from quantify_core.measurement import MeasurementControl

from qsea.experiments import dry_run
from qsea.experiments.calibration_nodes import CalibrationNodes
from qsea.experiments.datadir import set_datadir


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # the Q1ASM assembler writes scratch files to the cwd
    set_datadir(tmp_path)
    agent = dry_run.dummy_agent()
    meas_ctrl = MeasurementControl("meas_ctrl")
    meas_ctrl.verbose(False)
    nodes = CalibrationNodes(agent, meas_ctrl, 216e-9)
    yield nodes, agent.quantum_device.get_element("qubit1"), tmp_path
    Instrument.close_all()


def test_readout_calibration_on_simulated_blobs(setup):
    nodes, qubit, _ = setup
    with dry_run.simulate(dry_run.readout_data(g_centroid=0.01 + 0.01j, e_centroid=0.03 + 0.03j,
                                               measurement_noise=0.003)):
        ok, fidelity = nodes.readout_calibration(qubit, num_points=600)
    assert ok and fidelity > 0.95
    assert np.isfinite(qubit.measure.acq_threshold)
    tuids = nodes.history[-1]["tuids"]
    assert tuids
    # the snapshot holds the device, in qqea's layout too
    snapshot = load_snapshot(tuids[0])["instruments"]
    assert snapshot["quantum_device"]["parameters"]["device"]["value"]["elements"]["qubit1"]
    assert snapshot["qubit1"]["submodules"]["clock_freqs"]["parameters"]["f01"]["value"] == qubit.clock_freqs.f01


def test_drag_runs_on_the_dummy_cluster_and_saves_raw_data(setup):
    nodes, qubit, datadir = setup
    beta_before = qubit.rxy.beta
    ok, value = nodes.drag_calibration(qubit, motzoi_list=np.linspace(-0.1, 0.1, 5), repetitions=10)
    # the dummy cluster returns no real signal, so the fit result is meaningless;
    # what matters is that it ran, kept the (ok, value) contract and saved the data
    assert isinstance(ok, bool)
    if not ok:
        assert qubit.rxy.beta == beta_before
    tuids = nodes.history[-1]["tuids"]
    assert len(tuids) == 1
    assert list(datadir.glob(f"*/{tuids[0]}*/snapshot.json"))
