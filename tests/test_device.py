"""qsea.device: converting a qqea snapshot, and loading the lab configs."""

import json
from pathlib import Path

import numpy as np
import pytest
from qblox_scheduler.backends.qblox_backend import QbloxHardwareCompilationConfig
from qblox_scheduler.waveforms import drag

from qsea.device import (
    convert_hardware_config,
    drag_beta_from_motzoi,
    load_hardware_config,
    load_quantum_device,
    quantum_device_from_snapshot,
    save_quantum_device,
)
from qsea.schedules.edges import CompositeiSWAPEdge

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


def _params(**values):
    return {"parameters": {k: {"value": v} for k, v in values.items()}}


def _snapshot():
    """The structure of a qqea dataset snapshot, with made-up values."""
    qubit = {"submodules": {
        "reset": _params(duration=250e-6),
        "rxy": _params(amp180=0.7, motzoi=-0.05, duration=100e-9, reference_magnitude=None),
        "measure": _params(pulse_type="SquarePulse", pulse_amp=0.2, pulse_duration=4.4e-6,
                           acq_channel=1, acq_delay=216e-9, integration_time=4.4e-6,
                           acq_weights_a="[]", acq_weights_b="[]",
                           acq_weights_sampling_rate=1e9, acq_threshold=0.01, acq_rotation=45.0),
        "ports": _params(microwave="qubit1:mw", flux="qubit1:fl", readout="qubit1:res"),
        "clock_freqs": _params(f01=4.5e9, f12=float("nan"), readout=7.1e9),
    }}
    edge = {"submodules": {"iswap": _params(pulse_frequency=2.6e8, pulse_amp=9, pulse_duration=495e-9,
                                            ac_stark_phase_q1=-120.0, ac_stark_phase_q2=150.0)}}
    hardware = {"config_type": "quantify_scheduler.backends.qblox_backend.QbloxHardwareCompilationConfig",
                "hardware_description": {}, "connectivity": {"graph": []}}
    return {"instruments": {
        "qubit1": qubit, "qubit2": json.loads(json.dumps(qubit).replace("qubit1", "qubit2")),
        "qubit1_qubit2": edge,
        "quantum_device": _params(elements=["qubit1", "qubit2"], edges=["qubit1_qubit2"],
                                  cfg_sched_repetitions=200, keep_original_schedule=True,
                                  hardware_config=hardware),
    }}


def test_beta_reproduces_the_quantify_scheduler_drag_pulse():
    duration, amp, motzoi = 100e-9, 0.7, -0.05
    t = np.arange(0, duration, 1e-9)
    # quantify-scheduler 0.23 drag(): derivative -motzoi (t - mu) / sigma G(t), and by default
    # both parts shifted so their first and last samples average to zero
    sigma, mu = duration / 8, t[0] + duration / 2
    gauss = amp * np.exp(-0.5 * (t - mu) ** 2 / sigma**2)
    deriv = -motzoi * (t - mu) / sigma * gauss
    gauss, deriv = gauss - (gauss[0] + gauss[-1]) / 2, deriv - (deriv[0] + deriv[-1]) / 2
    old = gauss + 1j * deriv
    new = drag(t=t, amplitude=amp, beta=drag_beta_from_motzoi(motzoi, duration),
               duration=duration, nr_sigma=4, phase=0)
    np.testing.assert_allclose(new, old, atol=1e-15)


def test_device_from_snapshot():
    with pytest.warns(UserWarning) as record:  # nothing is lost from the synthetic snapshot ...
        device = quantum_device_from_snapshot(_snapshot())
        import warnings
        warnings.warn("sentinel")                # ... so only this warning is raised
    assert [str(w.message) for w in record] == ["sentinel"]

    q2 = device.get_element("qubit2")
    assert q2.rxy.beta == pytest.approx(-0.05 * 100e-9 / 8)
    assert q2.measure.acq_label == 1
    assert q2.measure.acq_weights_a is None
    assert q2.measure.acq_threshold == 0.01
    assert np.isnan(q2.clock_freqs.f12)
    edge = device.get_edge("qubit1_qubit2")
    assert isinstance(edge, CompositeiSWAPEdge)
    assert edge.iswap.pulse_duration == 495e-9
    assert device.cfg_sched_repetitions == 200


def test_hardware_config_conversion():
    config = convert_hardware_config(_snapshot()["instruments"]["quantum_device"]["parameters"]
                                     ["hardware_config"]["value"])
    assert config["config_type"] == "QbloxHardwareCompilationConfig"


def test_lab_configs_load(tmp_path):
    device = load_quantum_device(CONFIGS / "quantum_device.json")
    assert set(device.elements) == {"qubit1", "qubit2", "snail"}
    assert isinstance(device.get_edge("qubit1_qubit2"), CompositeiSWAPEdge)
    save_quantum_device(device, tmp_path / "device.json")
    assert load_quantum_device(tmp_path / "device.json").to_json() == device.to_json()
    QbloxHardwareCompilationConfig.model_validate(load_hardware_config(CONFIGS / "hardware_config.json"))
