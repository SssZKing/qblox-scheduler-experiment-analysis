"""Helpers the reference comparison does not exercise on its own."""

import numpy as np
import pytest
from qblox_applications.qblox_scheduler.superconducting.transmon import BasicTransmonElement
from qblox_scheduler import QuantumDevice
from qblox_scheduler.backends import SerialCompiler
from qblox_scheduler.schedules.schedule import TimeableSchedule

from qsea.schedules import single_qubit as sq
from qsea.schedules import twpa
from qsea.schedules.acquisition import acq_protocol_name, average_repetitions
from qsea.schedules.edges import CompositeiSWAPEdge
from qsea.schedules.gates import index_to_operation


@pytest.fixture
def device():
    qd = QuantumDevice(name="test_device")
    for name, f01, ro in (("qubit1", 5.0e9, 7.0e9), ("qubit2", 5.26e9, 7.1e9)):
        q = BasicTransmonElement(name=name)
        q.clock_freqs.f01, q.clock_freqs.readout = f01, ro
        q.rxy.amp180, q.rxy.duration = 0.3, 40e-9
        q.measure.pulse_amp, q.measure.pulse_duration = 0.1, 2e-6
        q.measure.acq_delay, q.measure.integration_time = 120e-9, 1.8e-6
        q.reset.duration = 200e-6
        qd.add_element(q)
    edge = CompositeiSWAPEdge(parent_element_name="qubit1", child_element_name="qubit2")
    edge.iswap.pulse_duration = 400e-9
    edge.iswap.ac_stark_phase_q1 = 98.5
    qd.add_edge(edge)
    yield qd
    twpa._TWPA_PUMP.clear()


def _markers(qd, schedule, port):
    compiled = SerialCompiler(name="test").compile(schedule, config=qd.generate_compilation_config())
    table = compiled.timing_table.data
    return int(((table.port == port) & table.operation.str.startswith("MarkerPulse")).sum())


def test_twpa_pump_setting(device):
    q1 = device.get_element("qubit1")
    build = lambda: sq.t1_sched(times=np.array([1e-6, 2e-6]), qubit=q1)  # noqa: E731
    assert twpa.twpa_pump_enabled("qubit1")
    assert _markers(device, build(), "qubit1:switch") == 2

    twpa.set_twpa_pump(q1, False)
    assert not twpa.twpa_pump_enabled("qubit1")
    assert twpa.twpa_pump_enabled("qubit2")
    assert twpa.twpa_pump_settings() == {"qubit1": False}
    assert _markers(device, build(), "qubit1:switch") == 0

    twpa.set_twpa_pump("qubit1", True)
    assert _markers(device, build(), "qubit1:switch") == 2


def test_acquisition_names():
    assert acq_protocol_name("ThresholdedAcquisition") == "ThresholdedIQIntegration"
    assert acq_protocol_name("SSBIntegrationComplex") == "IQIntegration"
    assert acq_protocol_name("Trace") == "Trace"
    assert average_repetitions("average") is True
    assert average_repetitions("append") is False
    with pytest.raises(ValueError):
        average_repetitions("sum")


def test_iswap_edge_round_trip(device):
    restored = QuantumDevice.from_json(device.to_json())
    edge = restored.get_edge("qubit1_qubit2")
    assert isinstance(edge, CompositeiSWAPEdge)
    assert edge.iswap.pulse_duration == 400e-9
    assert edge.iswap.ac_stark_phase_q1 == 98.5
    config = restored.generate_device_config().edges["qubit1_qubit2"]["iSWAP"]
    assert config.factory_kwargs["pulse_duration"] == 400e-9


def test_index_to_operation_still_returns_a_schedule():
    assert isinstance(index_to_operation(["qubit1", "qubit2"], 16e-9, 5760), TimeableSchedule)
    assert index_to_operation(["qubit1"], 0.0, 0) is None  # the identity
