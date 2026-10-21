"""Check that every ported ``qsea.schedules`` builder compiles to the same schedule as qqea.

Builds each case (the same 68 cases and mock two-qubit device as qqea's
``tools/compare_schedules.py``) with qblox-scheduler, compiles it to device level
and compares the timing table (start time, duration, port, clock, acquisition flag,
operation type and its key arguments) with the reference dumped from qqea in
``tests/schedules/reference/qqea-4de2850.json`` (see the README there).

What is expected to differ, and is normalised before comparing:

- Renamed operations and arguments: ``SSBIntegrationComplex`` -> ``IQIntegration``,
  ``ThresholdedAcquisition`` -> ``ThresholdedIQIntegration``, ``amp``/``G_amp`` ->
  ``amplitude``, ``D_amp`` -> ``beta``, ``acq_channel`` -> ``acq_label``,
  ``bin_mode`` -> ``average_segment_repetitions``, ``SetClockFrequency(clock_freq_new=)`` ->
  ``SetClockFrequency(frequency=)``.
- qblox-scheduler 1.0 turns ``repetitions`` into a loop whose body starts with a
  ``ResetClockPhase`` of every clock used and a 4 ns ``IdlePulse``
  (``qblox_scheduler.compilation.schedule_repetitions_to_loop``). Those rows are
  dropped and the 4 ns shift is taken off.
- Zero-length ``IdlePulse`` rows are dropped on both sides: they do nothing, and
  ``qsea.schedules.gates.add_layers`` uses them as anchors where qqea had sub-schedules.
- A multi-qubit ``Reset`` shows up as the ``IdlePulse`` it compiles to; both count as an
  idle on the baseband clock.

No instruments are touched: pump generators and the instrument coordinator are fakes,
and compilation stops before the hardware backend.

- The reference's ``D_amp`` is compared as ``beta = D_amp * duration / 8`` (see
  ``qsea.device.drag_beta_from_motzoi``); compared values are rounded to 10 digits.

Run it from the repo root in ``qbs_env``::

    python tools/compare_schedules.py
    python tools/compare_schedules.py --only rabi,t1 --verbose

``--device configs/quantum_device.json --reference tests/schedules/reference/qqea-4de2850-lab.json``
compares the lab device (converted with ``qsea.device``) against qqea built with the
snapshot it came from. A case that fails on both sides (e.g. a clock left at NaN) counts
as the same.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
import traceback

sys.dont_write_bytecode = True

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFERENCE = os.path.join(REPO, "tests", "schedules", "reference", "qqea-4de2850.json")

# The DRAG and readout-optimization runners run on the cluster; they move with the
# calibration nodes (MIGRATION_PLAN.md, phase 4).
PENDING = {
    "readout_freq_optimization": "phase 4 (experiments.runners)",
    "readout_amp_optimization": "phase 4 (experiments.runners)",
    "readout_len_optimization": "phase 4 (experiments.runners)",
    "readout_weight_optimization": "phase 4 (experiments.runners)",
    "drag_calibration": "phase 4 (experiments.runners)",
}

# --------------------------------------------------------------------------
# Mock device (same values as qqea's tool)
# --------------------------------------------------------------------------

ELEMENT_PARAMS = {
    "qubit1": {
        "clock_freqs": {"f01": 5.00e9, "f12": 4.80e9, "readout": 7.00e9},
        "rxy": {"amp180": 0.30, "duration": 40e-9},
        "measure": {
            "pulse_amp": 0.10,
            "pulse_duration": 2.0e-6,
            "acq_delay": 120e-9,
            "integration_time": 1.8e-6,
            "acq_label": 0,
        },
        "reset": {"duration": 200e-6},
    },
    "qubit2": {
        "clock_freqs": {"f01": 5.26e9, "f12": 5.05e9, "readout": 7.10e9},
        "rxy": {"amp180": 0.32, "duration": 40e-9},
        "measure": {
            "pulse_amp": 0.12,
            "pulse_duration": 1.6e-6,
            "acq_delay": 120e-9,
            "integration_time": 1.4e-6,
            "acq_label": 1,
        },
        "reset": {"duration": 200e-6},
    },
}
EDGE_PARAMS = {
    "pulse_frequency": 259.8e6,
    "pulse_amp": 5.0,
    "pulse_duration": 400e-9,
    "ac_stark_phase_q1": 98.5,
    "ac_stark_phase_q2": -106.5,
}


def build_device(device_path=None):
    if device_path:
        from qsea.device import load_quantum_device

        qd = load_quantum_device(device_path)
        return qd, qd.get_element("qubit1"), qd.get_element("qubit2")

    from qblox_applications.qblox_scheduler.superconducting.transmon import BasicTransmonElement
    from qblox_scheduler import QuantumDevice

    from qsea.schedules.edges import CompositeiSWAPEdge

    qd = QuantumDevice(name="compare_device")
    elements = {}
    for name, params in ELEMENT_PARAMS.items():
        q = BasicTransmonElement(name=name)
        for sub, values in params.items():
            for p, v in values.items():
                setattr(getattr(q, sub), p, v)
        qd.add_element(q)
        elements[name] = q
    edge = CompositeiSWAPEdge(parent_element_name="qubit1", child_element_name="qubit2")
    for p, v in EDGE_PARAMS.items():
        setattr(edge.iswap, p, v)
    qd.add_edge(edge)
    return qd, elements["qubit1"], elements["qubit2"]


class FakeSource:
    """Stands in for a signal generator; records every call."""

    def __init__(self, name, log):
        self._name = name
        self._log = log

    def __getattr__(self, attr):
        def call(*args, **kwargs):
            self._log.append([self._name, attr, [_jsonable(a) for a in args], sorted(kwargs)])

        return call


class FakeCoordinator:
    """Stands in for the InstrumentCoordinator; keeps the compiled schedules."""

    def __init__(self):
        self.compiled = []

    def prepare(self, compiled_schedule):
        self.compiled.append(compiled_schedule)

    def start(self):
        pass

    def wait_done(self, timeout_sec=None):
        pass

    def retrieve_acquisition(self):
        return None


def _jsonable(x):
    import numpy as np

    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    return x if isinstance(x, (int, float, str, bool, type(None))) else repr(x)


# --------------------------------------------------------------------------
# Cases: (case name, module, function, kwargs builder), copied from qqea's tool
# --------------------------------------------------------------------------


def cases():
    import numpy as np

    lin = np.linspace
    times = np.array([100e-9, 1.1e-6, 2.1e-6])
    ro_freqs = lin(7.000e9, 7.002e9, 3)
    spec = dict(acquisition_delay=120e-9, integration_time=1.8e-6, port="qubit1:res", clock="qubit1.ro")

    sq, tq = "single_qubit", "two_qubit"
    c = [
        ("time_of_flight", sq, "time_of_flight_calibration", lambda e: dict(
            port="qubit1:res", clock="qubit1.ro", pulse_duration=1e-6, pulse_amp=0.1,
            acq_duration=2e-6, time_of_flight=200e-9, TWPA_delay=-36e-9)),
        ("time_of_flight_drag", sq, "time_of_flight_calibration", lambda e: dict(
            port="qubit1:res", clock="qubit1.ro", pulse_duration=1e-6, pulse_amp=0.1,
            acq_duration=2e-6, time_of_flight=200e-9, pulse_type="DRAG")),
        ("sweep_optimal", sq, "sweep_optimal_TWPA", lambda e: dict(
            TWPA_pump=e["pump"], TWPA_freq=8e9, TWPA_power=-5.0, pulse_amp=0.1,
            pulse_duration=2e-6, frequencies=ro_freqs, **spec)),
        ("heterodyne", sq, "heterodyne_spec_sched_nco", lambda e: dict(
            pulse_amp=0.1, pulse_duration=2e-6, frequencies=ro_freqs, **spec)),
        ("multiplexed_heterodyne", sq, "multiplexed_heterodyne_spec_sched_nco", lambda e: dict(
            pulse_amp=0.1, pulse_duration=2e-6, frequencies_qubit1=ro_freqs,
            frequencies_qubit2=lin(7.100e9, 7.102e9, 3), frequencies_idx=np.arange(3),
            acquisition_delay=120e-9, integration_time=1.8e-6,
            ports=["qubit1:res", "qubit2:res"], clocks=["qubit1.ro", "qubit2.ro"])),
        ("two_tone", sq, "two_tone_spec_sched_nco", lambda e: dict(
            spec_pulse_amp=0.05, spec_pulse_duration=10e-6, spec_pulse_port="qubit1:mw",
            spec_pulse_clock="qubit1.01", spec_pulse_frequencies=lin(4.99e9, 5.01e9, 3),
            ro_pulse_amp=0.1, ro_pulse_duration=2e-6, ro_pulse_delay=200e-9,
            ro_pulse_port="qubit1:res", ro_pulse_clock="qubit1.ro", ro_pulse_frequency=7e9,
            ro_acquisition_delay=120e-9, ro_integration_time=1.8e-6, init_duration=10e-6)),
        ("multiplexed_two_tone", sq, "multiplexed_two_tone_spec_sched_nco", lambda e: dict(
            qubits=[e["q1"], e["q2"]], pulse_amp=0.05, pulse_duration=10e-6,
            frequencies_qubit1=lin(4.99e9, 5.01e9, 3), frequencies_qubit2=lin(5.25e9, 5.27e9, 3),
            frequencies_idx=np.arange(3), ro_pulse_delay=200e-9)),
        ("rabi", sq, "rabi_sched", lambda e: dict(
            pulse_amp=lin(0, 0.5, 3), pulse_duration=40e-9, frequency=5e9, qubit=e["q1"])),
        ("rabi_amplification", sq, "rabi_amplification", lambda e: dict(
            pulse_amp=lin(0.25, 0.35, 3), pulse_duration=40e-9, pi_number=3, frequency=5e9,
            qubit=e["q1"])),
        ("ramsey", sq, "ramsey_sched", lambda e: dict(
            times=times, qubit=e["q1"], artificial_detuning=1e6)),
        ("stark_ramsey", sq, "stark_ramsey_sched", lambda e: dict(
            times=times, qubit=e["q1"], stark_amp=0.1, stark_freq=5.05e9)),
        ("coupled_ramsey", sq, "coupled_ramsey_sched", lambda e: dict(
            times=times, qubit=e["q1"], qubit_c=e["q2"])),
        ("coupled_phase_ramsey", sq, "coupled_phase_ramsey_sched", lambda e: dict(
            phases=lin(0, 360, 3), qubit=e["q1"], qubit_c=e["q2"])),
        ("echo", sq, "echo_sched", lambda e: dict(times=times, qubit=e["q1"])),
        ("t1", sq, "t1_sched", lambda e: dict(times=times, qubit=e["q1"])),
    ]
    for case in (1, 2, 3):
        c += [
            (f"t1_and_t2_case{case}", sq, "t1_and_t2", lambda e, case=case: dict(
                times=times, qubit=e["q1"], case=case, artificial_detuning=1e6)),
            (f"multi_qubit_t1_and_t2_case{case}", sq, "multi_qubit_t1_and_t2",
             lambda e, case=case: dict(times=times, qubit_specifier=[e["q1"], e["q2"]], case=case)),
        ]
    c += [
        ("multiplexed_readout_calibration", sq, "multiplexed_readout_calibration_sched",
         lambda e: dict(qubits=[e["q1"], e["q2"]], prepared_states=[0, 1])),
        ("readout_calibration", sq, "readout_calibration_sched", lambda e: dict(
            qubit=e["q1"], prepared_states=[0, 1, 2])),
        ("readout_freq_optimization", sq, "readout_freq_optimization_TWPA", lambda e: dict(
            qubit=e["q1"], frequencies=lin(7.000e9, 7.001e9, 2), instrument_coordinator=e["ic"],
            quantum_device=e["qd"])),
        ("readout_amp_optimization", sq, "readout_amp_optimization_TWPA", lambda e: dict(
            qubit=e["q1"], amps=[0.1, 0.2], instrument_coordinator=e["ic"], quantum_device=e["qd"])),
        ("readout_len_optimization", sq, "readout_len_optimization_TWPA", lambda e: dict(
            qubit=e["q1"], lens=[1e-6, 2e-6], instrument_coordinator=e["ic"], quantum_device=e["qd"])),
        ("readout_weight_optimization", sq, "readout_weight_optimization_TWPA", lambda e: dict(
            qubit=e["q1"], instrument_coordinator=e["ic"], quantum_device=e["qd"])),
        ("allxy", sq, "allxy_sched", lambda e: dict(qubit=e["q1"])),
        ("drag_calibration", sq, "DRAG_calibration_sched", lambda e: dict(
            qubit=e["q1"], motzoi_list=lin(-0.1, 0.1, 3), instrument_coordinator=e["ic"],
            quantum_device=e["qd"])),
        ("dressed_e_cavity", sq, "dressed_e_cavity", lambda e: dict(
            pulse_amp=0.1, pulse_duration=2e-6, frequencies=ro_freqs, qubit="qubit1", **spec)),
        ("f_state_spec", sq, "f_state_spec_sched_nco", lambda e: dict(
            spec_pulse_amp=0.05, spec_pulse_duration=10e-6, spec_pulse_port="qubit1:fs",
            spec_pulse_clock="qubit1.12", spec_pulse_frequencies=lin(4.79e9, 4.81e9, 3),
            qubit=e["q1"])),
        ("f_state_rabi", sq, "f_state_rabi_sched", lambda e: dict(
            pulse_amp=lin(0, 0.5, 3), pulse_duration=400e-9, frequency=4.8e9, qubit=e["q1"])),
        ("f_state_cavity", sq, "f_state_cavity", lambda e: dict(
            pulse_amp=0.1, pulse_duration=2e-6, frequencies=ro_freqs, qubit="qubit1", **spec)),
        ("f_state_t1_case1", sq, "f_state_t1", lambda e: dict(times=times, qubit=e["q1"], case=1)),
        ("f_state_t1_case2", sq, "f_state_t1", lambda e: dict(times=times, qubit=e["q1"], case=2)),
        ("multiplex_IQ", sq, "multiplex_IQ", lambda e: dict(
            qubit=e["q1"], prepared_states=[0, 1, 2], multiplexing_freq=[7.000e9, 7.001e9, 7.002e9])),
        ("RO_raw_trace", sq, "RO_raw_trace", lambda e: dict(
            qubit=e["q1"], trace_time=2e-6, prepared_states=[0, 1, 2],
            multiplexing_freq=[7.000e9, 7.001e9, 7.002e9])),
        ("rabi_population_case1", sq, "rabi_population", lambda e: dict(
            qubit=e["q1"], case=1, angles=lin(0, 180, 3))),
        ("rabi_population_case2", sq, "rabi_population", lambda e: dict(
            qubit=e["q1"], case=2, angles=lin(0, 180, 3))),
        ("snail_swap", sq, "SNAIL_swap_sched", lambda e: dict(
            pulse_frequency=6e9, pulse_amp=np.array([-10.0, -5.0]), pulse_duration=200e-9,
            snail_drive=e["snail"], qubit_specifier=[e["q1"], e["q2"]], qubit_e=[e["q1"]],
            swap_type="iSWAP")),
        ("snail_spec", sq, "SNAIL_spec_sched", lambda e: dict(
            spec_pulse_amp=-10.0, spec_pulse_duration=2e-6, spec_pulse_frequencies=lin(6e9, 6.01e9, 3),
            snail_drive=e["snail"], qubit=e["q1"], init_duration=10e-6)),
        ("pump_heterodyne", sq, "pump_heterodyne_spec_sched_nco", lambda e: dict(
            pump_frequency=6e9, pump_amp=-10.0, pump_duration=200e-9, snail_drive=e["snail"],
            pulse_amp=0.1, pulse_duration=2e-6, frequencies=ro_freqs, **spec)),
        ("pump_t1", sq, "pump_t1_sched", lambda e: dict(
            times=times, snail_drive=e["snail"], qubit_specifier=[e["q1"], e["q2"]], qubit_e=[e["q1"]])),
        ("pump_ramsey", sq, "pump_ramsey_sched", lambda e: dict(
            times=times, snail_drive=e["snail"], qubit_specifier=[e["q1"], e["q2"]], qubit_e=[e["q1"]])),
        ("pump_t1_and_t2_case1", sq, "pump_t1_and_t2_sched", lambda e: dict(
            times=times, snail_drive=e["snail"], qubit_specifier=[e["q1"], e["q2"]],
            qubit_e=[e["q1"]], case=1)),
        ("pump_RPM", sq, "pump_RPM", lambda e: dict(
            qubit=e["q1"], case=1, angles=lin(0, 180, 3), pump_frequency=6e9, pump_amp=-10.0,
            pump_duration=200e-9, snail_drive=e["snail"])),
        ("cavity_charging", sq, "cavity_charging", lambda e: dict(
            qubit=e["q1"], pulse_amp=[0.1, 0.2], frequency=7e9, port="qubit1:res", clock="qubit1.ro")),
    ]

    pair = lambda e: [e["q1"], e["q2"]]  # noqa: E731
    c += [
        ("rb_1q", tq, "randomized_benchmarking_schedule", lambda e: dict(
            qubit_specifier=e["q1"], lengths=[1, 3, 1, 1], seeds=[11, 12, 0, 0])),
        ("rb_2q", tq, "randomized_benchmarking_schedule", lambda e: dict(
            qubit_specifier=pair(e), lengths=[1, 2, 1, 1], seeds=[11, 12, 0, 0])),
        ("simultaneous_rb", tq, "simultaneous_randomized_benchmarking_schedule", lambda e: dict(
            qubit_specifier=pair(e), lengths=[1, 3, 1, 1], seeds=[11, 12, 0, 0])),
        ("iswap_pulsed_pump", tq, "iswap_pulsed_pump_schedule", lambda e: dict(
            qubit_specifier=pair(e), lengths=[1, 3])),
        ("iswap_pulsed_pump_spaced", tq, "iswap_pulsed_pump_schedule", lambda e: dict(
            qubit_specifier=pair(e), lengths=[1, 3], iswap_spacing=100e-9)),
        ("iswap_tail_1q", tq, "iswap_tail_1q_schedule", lambda e: dict(
            qubit_specifier=pair(e), lengths=[1, 2], gap=40e-9)),
        ("pump_probe_ramsey", tq, "pump_probe_ramsey_schedule", lambda e: dict(
            qubit_specifier=pair(e), delays=[0.0, 40e-9])),
        ("pump_probe_swap", tq, "pump_probe_swap_schedule", lambda e: dict(
            qubit_specifier=pair(e), durations=[0.0, 200e-9])),
        ("iswap_virtual_z", tq, "iswap_virtual_z_schedule", lambda e: dict(
            qubit_specifier=pair(e), lengths=[1, 2], angle=10.0, gate_idx=16)),
        ("iswap_RPE_f", tq, "iswap_RPE_f", lambda e: dict(
            qubit_specifier=pair(e), lengths=[1, 2], quantum_device=e["qd"])),
        ("iswap_RPE_f_y", tq, "iswap_RPE_f", lambda e: dict(
            qubit_specifier=pair(e), lengths=[1, 2], quantum_device=e["qd"], final_axis="y")),
        ("iswap_RPE_theta_sum", tq, "iswap_RPE_theta_sum", lambda e: dict(
            qubit_specifier=pair(e), lengths=[1, 2], quantum_device=e["qd"])),
        ("iswap_RPE_d", tq, "iswap_RPE_d", lambda e: dict(
            qubit_specifier=pair(e), lengths=[1, 2], sqrt_iswap_duration=200e-9,
            quantum_device=e["qd"])),
        ("iswap_delay", tq, "iswap_delay_schedule", lambda e: dict(
            qubit_specifier=pair(e), gate_idx=16, delays=[0.0, 40e-9])),
        ("tomography_pre_build", tq, "tomography_pre_build", lambda e: dict(
            qubit_specifier=pair(e), operation_state_idx=5760, quantum_device=e["qd"])),
        ("tomography", tq, "tomography_schedule", lambda e: dict(
            qubit_specifier=pair(e), operation_state_idx=5760, instrument_coordinator=e["ic"],
            quantum_device=e["qd"], correction_phase=e["mod"].tomography_pre_build(
                pair(e), 5760, e["qd"]))),
        ("tomography_1q", tq, "tomography_schedule", lambda e: dict(
            qubit_specifier=e["q1"], operation_state_idx=16, instrument_coordinator=e["ic"],
            quantum_device=e["qd"])),
        ("process_tomography_pre_build", tq, "process_tomography_pre_build", lambda e: dict(
            qubit_specifier=pair(e), operation_state_idx=5760, experiment_list=[0, 7, 40],
            quantum_device=e["qd"])),
        ("process_tomography", tq, "process_tomography_schedule", lambda e: dict(
            qubit_specifier=pair(e), operation_state_idx=5760, experiment_list=[0, 7, 40],
            instrument_coordinator=e["ic"], quantum_device=e["qd"],
            correction_phase=e["mod"].process_tomography_pre_build(
                pair(e), 5760, [0, 7, 40], e["qd"]))),
        ("gst_pre_build", tq, "GST_pre_build", lambda e: dict(
            qubit_specifier=pair(e), experiment_list=_gst_circuits(), quantum_device=e["qd"])),
        ("gst", tq, "GST_schedule", lambda e: dict(
            qubit_specifier=pair(e), experiment_list=_gst_circuits(), instrument_coordinator=e["ic"],
            quantum_device=e["qd"], correction_phase=e["mod"].GST_pre_build(
                pair(e), _gst_circuits(), e["qd"]))),
    ]
    return c


def _gst_circuits():
    from pygsti.circuits import Circuit

    return [
        Circuit([("Gxpi2", 0), ("Gypi2", 1)], line_labels=(0, 1)),
        Circuit([("Gxpi2", 0), ("Giswap", 0, 1), ("Gympi2", 1)], line_labels=(0, 1)),
        Circuit([("Giswap", 0, 1), ("Giswap", 0, 1), ("Gx", 0)], line_labels=(0, 1)),
    ]


# --------------------------------------------------------------------------
# Build one side
# --------------------------------------------------------------------------


def _rows(schedule):
    table = schedule.timing_table.data
    rows = []
    for r in table.itertuples(index=False):
        rows.append([
            round(float(r.abs_time) * 1e12, 3),  # ps
            round(float(r.duration) * 1e12, 3),
            str(r.port),
            str(r.clock),
            bool(r.is_acquisition),
            str(r.operation),
        ])
    rows.sort(key=lambda row: (row[0], row[2] or "", row[3] or "", row[5]))
    return rows


def dump(only, device_path=None):
    from qblox_scheduler.backends import SerialCompiler
    from qblox_scheduler.schedules.schedule import TimeableScheduleBase

    results = {}
    for name, module, func, make_kwargs in cases():
        if only and not any(o in name for o in only):
            continue
        if name in PENDING:
            results[name] = {"status": "pending", "reason": PENDING[name]}
            continue
        qd, q1, q2 = build_device(device_path)
        log = []
        mod = importlib.import_module(f"qsea.schedules.{module}")
        env = {
            "qd": qd, "q1": q1, "q2": q2, "ic": FakeCoordinator(), "mod": mod,
            "pump": FakeSource("TWPA_pump", log), "snail": FakeSource("snail_drive", log),
        }
        entry = {"function": f"{module}.{func}"}
        try:
            value = getattr(mod, func)(**make_kwargs(env))
            schedules = list(env["ic"].compiled)
            if isinstance(value, TimeableScheduleBase):
                schedules.append(SerialCompiler(name="compare").compile(
                    schedule=value, config=qd.generate_compilation_config()
                ))
                entry["value"] = None
            else:
                entry["value"] = _jsonable(value)
            entry["schedules"] = [_rows(s) for s in schedules]
            entry["calls"] = log
            entry["status"] = "ok"
        except Exception as exc:  # noqa: BLE001  recorded and reported
            entry["status"] = "error"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["traceback"] = traceback.format_exc(limit=-4)
        results[name] = entry
    return results


# --------------------------------------------------------------------------
# Normalise and compare
# --------------------------------------------------------------------------

OP_RENAMES = {
    "SSBIntegrationComplex": "IQIntegration",
    "ThresholdedAcquisition": "ThresholdedIQIntegration",
}
ARG_RENAMES = {
    "amp": "amplitude", "G_amp": "amplitude", "D_amp": "beta", "acq_channel": "acq_label",
    "clock_freq_new": "frequency",
}
# Arguments compared besides timing, port and clock, with the value assumed when absent.
COMPARED_ARGS = {
    "amplitude": None, "beta": 0.0, "phase": 0.0, "theta": None, "phi": None,
    "frequency": None, "phase_shift": None, "acq_label": None, "average": True,
}
_ARG = re.compile(r"(\w+)=('[^']*'|[^,()]+)")
PREAMBLE_SHIFT_PS = 4000.0


def _parse_op(op):
    name = op.split("(", 1)[0]
    args = {}
    for key, raw in _ARG.findall(op[len(name):]):
        key = ARG_RENAMES.get(key, key)
        raw = raw.strip()
        if key == "bin_mode":
            key, value = "average", raw.strip("'") != "append"
        elif key == "average_segment_repetitions":
            key, value = "average", raw == "True"
        else:
            try:
                value = float(raw)
            except ValueError:
                value = raw.strip("'")
        if key in COMPARED_ARGS:
            args[key] = value
    return OP_RENAMES.get(name, name), args


def _round(value):
    return float(f"{value:.10g}") if isinstance(value, float) else value


def _norm_rows(rows, new_side):
    out = []
    if new_side:
        # drop the repetition-loop preamble: ResetClockPhase of every clock and an
        # IdlePulse(4 ns), all at t = 0
        body = []
        for r in rows:
            if r[0] == 0.0 and (r[5].startswith("ResetClockPhase(") and r[1] == 0.0
                                or r[5] == "IdlePulse(duration=4e-09)"):
                continue
            body.append([r[0] - PREAMBLE_SHIFT_PS, *r[1:]])
        rows = body
    for t, dur, port, clock, is_acq, op in rows:
        name, args = _parse_op(op)
        if name == "DRAGPulse" and not new_side and "beta" in args:
            args["beta"] = args["beta"] * dur * 1e-12 / 8  # D_amp -> beta
        if name in ("IdlePulse", "Reset") and clock == "cl0.baseband":
            if dur == 0.0:
                continue
            name = "Idle"
        full = {k: _round(args.get(k, d)) for k, d in COMPARED_ARGS.items()}
        out.append(json.dumps([t, dur, port, clock, is_acq, name, full], sort_keys=True))
    return sorted(out)


def _close(a, b):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


def compare(ref, new, verbose=False, limit=6):
    report, counts = [], {"same": 0, "different": 0, "error": 0, "pending": 0}
    for name, n in new.items():
        b = ref.get(name)
        if n["status"] == "pending":
            report.append(f"pending    {name}: {n['reason']}")
            counts["pending"] += 1
            continue
        if b["status"] == "error":
            if n["status"] == "error":
                report.append(f"same       {name} (fails on both sides: {n['error'][:90]})")
                counts["same"] += 1
            else:
                report.append(f"DIFFERENT  {name}: reference failed ({b['error'][:90]}), qsea did not")
                counts["different"] += 1
            continue
        if n["status"] == "error":
            report.append(f"ERROR      {name}: {n['error']}")
            if verbose:
                report.append(n["traceback"])
            counts["error"] += 1
            continue
        problems = []
        if len(b["schedules"]) != len(n["schedules"]):
            problems.append(f"    {len(b['schedules'])} vs {len(n['schedules'])} compiled schedules")
        else:
            for i, (rb, rn) in enumerate(zip(b["schedules"], n["schedules"])):
                sb, sn = _norm_rows(rb, False), _norm_rows(rn, True)
                if sb != sn:
                    problems.append(f"    schedule {i}: {len(sb)} vs {len(sn)} rows")
                    only_b, only_n = sorted(set(sb) - set(sn)), sorted(set(sn) - set(sb))
                    problems += [f"      - {r}" for r in only_b[:limit]]
                    problems += [f"      + {r}" for r in only_n[:limit]]
        if not _close(b["value"], n["value"]):
            problems.append(f"    return value {b['value']} vs {n['value']}")
        if b["calls"] != n["calls"]:
            problems.append(f"    instrument calls {b['calls']} vs {n['calls']}")
        if problems:
            report.append(f"DIFFERENT  {name}")
            report += problems
            counts["different"] += 1
        else:
            rows = sum(len(s) for s in b["schedules"])
            report.append(f"same       {name} ({rows} pulses/acquisitions)")
            counts["same"] += 1
    report.append("\n" + ", ".join(f"{v} {k}" for k, v in counts.items()))
    return "\n".join(report), counts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", default="", help="comma-separated substrings of case names")
    parser.add_argument("--verbose", action="store_true", help="show tracebacks of failing cases")
    parser.add_argument("--report", help="also write the report to this file")
    parser.add_argument("--device", help="QuantumDevice JSON to build with instead of the mock device")
    parser.add_argument("--reference", default=REFERENCE, help="reference dump (default %(default)s)")
    args = parser.parse_args()
    only = [o for o in args.only.split(",") if o]

    with open(args.reference) as f:
        ref = json.load(f)
    report, counts = compare(ref, dump(only, args.device), verbose=args.verbose)
    print(report)
    if args.report:
        with open(args.report, "w") as f:
            f.write(report + "\n")
    sys.exit(1 if counts["different"] or counts["error"] else 0)


if __name__ == "__main__":
    main()
