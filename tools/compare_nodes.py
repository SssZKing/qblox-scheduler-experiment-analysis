"""Check that the qsea calibration nodes behave like qqea's on the lab device.

Runs every node on a qblox-instruments dummy cluster with the lab device, in qqea (the
``qblox_env`` stack: quantify-scheduler, ``ScheduleGettable``, instrument coordinator) and in
qsea (qblox-scheduler ``HardwareAgent``, :class:`qsea.experiments.gettable.ScheduleGettable`).
Schedules are compiled and uploaded to the dummy cluster on both sides; only the acquired
data is replaced, by the same deterministic simulated signals (a resonator dip, Rabi
oscillations, decays, Ramsey fringes, IQ blobs, a DRAG crossing, readout traces). For each
node it compares the returned ``(ok, value)``, the device parameters the node wrote, and
every dataset it saved (variables, coordinates, their names/units and values, and the
dataset attributes).

The reference comes from qqea (Python 3.9, qblox_env pins, see
``tests/schedules/reference/README.md``)::

    python tools/compare_nodes.py dump-qqea --qqea <qqea checkout> --snapshot <snapshot.json> \\
        --out tests/experiments/reference/qqea-4de2850-lab-nodes.json

and is compared in ``qbs_env``::

    python tools/compare_nodes.py

qqea's DRAG node calibrates ``rxy.motzoi``, qsea's ``rxy.beta``; the reference's motzoi
values are compared as ``beta = motzoi * rxy.duration / 8``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
import traceback

import numpy as np

sys.dont_write_bytecode = True

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFERENCE = os.path.join(REPO, "tests", "experiments", "reference", "qqea-4de2850-lab-nodes.json")
ACQ_DELAY = 216e-9
DRAG_MOTZOI = np.linspace(-0.1, 0.1, 9)

# (case, node method, kwargs builder). ``e`` holds q1, q2 and the qubit pair.
CASES = [
    ("resonator_calibration", "resonator_calibration", lambda e: dict(
        qubit=e["q1"], frequency_setpoints=e["q1_ro"] + np.linspace(-2e6, 2e6, 81), repetitions=10)),
    ("rabi_calibration", "rabi_calibration", lambda e: dict(
        qubit=e["q1"], rabi_amplitude_setpoints=np.linspace(-1, 1, 41), repetitions=10)),
    ("rabi_amplification_calibration", "rabi_amplification_calibration", lambda e: dict(
        qubit=e["q1"], rabi_amplitude_setpoints=np.linspace(0.6, 0.8, 5),
        pi_number_setpoints=np.arange(0, 12, 2), repetitions=10)),
    ("ramsey_chevron_calibration", "ramsey_chevron_calibration", lambda e: dict(
        qubit=e["q1"], tau_setpoints=np.arange(0, 10e-6, 0.25e-6),
        detuning_setpoints=np.linspace(-300e3, 300e3, 5), repetitions=10)),
    ("T1_calibration", "T1_calibration", lambda e: dict(
        qubit=e["q1"], tau_setpoints=np.linspace(0, 80e-6, 21), repetitions=10)),
    ("T2_echo_calibration", "T2_echo_calibration", lambda e: dict(
        qubit=e["q1"], tau_setpoints=np.linspace(0, 80e-6, 21), repetitions=10)),
    ("multi_qubit_t1_and_t2", "multi_qubit_t1_and_t2", lambda e: dict(
        qubits=e["pair"], tau_setpoints=np.linspace(0, 60e-6, 16), repetitions=10)),
    ("drag_calibration", "drag_calibration", lambda e: dict(
        qubit=e["q1"], motzoi_list=DRAG_MOTZOI, repetitions=10)),
    ("allxy_calibration", "allxy_calibration", lambda e: dict(qubit=e["q1"], repetitions=10)),
    ("randomized_benchmarking", "randomized_benchmarking", lambda e: dict(
        qubit=e["q1"], length_setpoints=np.arange(0, 41, 10), seed_setpoints=np.array([11, 12, 13, 14]),
        repetitions=10)),
    ("readout_calibration", "readout_calibration", lambda e: dict(qubit=e["q1"], num_points=200)),
    ("multiplexed_readout_calibration", "multiplexed_readout_calibration", lambda e: dict(
        qubits=e["pair"], num_points=200)),
    ("ro_freq_optimization", "ro_freq_optimization", lambda e: dict(
        qubit=e["q1"], num_points=11, repetitions=50)),
    ("ro_amp_optimization", "ro_amp_optimization", lambda e: dict(
        qubit=e["q1"], num_points=11, repetitions=50)),
    ("ro_len_optimization", "ro_len_optimization", lambda e: dict(
        qubit=e["q1"], num_points=11, repetitions=50)),
    ("ro_weight_calibration", "ro_weight_calibration", lambda e: dict(qubit=e["q1"], repetitions=10)),
    ("stark_phase_difference_calibration", "stark_phase_difference_calibration", lambda e: dict(
        qubits=e["pair"], length_setpoints=np.arange(1, 8), repetitions=10)),
    ("stark_phase_sum_calibration", "stark_phase_sum_calibration", lambda e: dict(
        qubits=e["pair"], length_setpoints=np.arange(1, 8), repetitions=10)),
    ("stark_phase_quadrature_calibration", "stark_phase_quadrature_calibration", lambda e: dict(
        qubits=e["pair"], sum_length_setpoints=np.arange(0, 7), difference_length_setpoints=np.arange(1, 7),
        repetitions=10)),
]

ELEMENT_PARAMS = [("clock_freqs", "readout"), ("clock_freqs", "f01"), ("rxy", "amp180"), ("rxy", "beta"), ("rxy", "duration"),
                  ("measure", "pulse_amp"), ("measure", "pulse_duration"), ("measure", "integration_time"),
                  ("measure", "acq_threshold"), ("measure", "acq_rotation"), ("measure", "acq_weights_a"),
                  ("measure", "acq_weights_b")]


# --------------------------------------------------------------------------
# Simulated data (identical on both sides)
# --------------------------------------------------------------------------
G0, E0 = 0.004 + 0.012j, 0.019 + 0.003j  # |g> and |e> readout points


def _rng(*keys):
    seed = abs(hash(tuple(round(float(k), 6) for k in keys))) % (2 ** 32)
    return np.random.default_rng(seed)


def _iq(p, n, *keys, noise=2e-4):
    p = np.broadcast_to(np.asarray(p, dtype=float), (n,))
    rng = _rng(n, *keys)
    return G0 + p * (E0 - G0) + noise * (rng.standard_normal(n) + 1j * rng.standard_normal(n))


def _arr(value, n):
    a = np.atleast_1d(np.asarray(value, dtype=float)).ravel()
    return np.resize(a, n)


def simulated_points(function_name, kw, n, channel=0):
    """The complex points a gettable would return for ``function_name(**kw)``, length ``n``."""
    idx = np.arange(n, dtype=float)
    if function_name == "heterodyne_spec_sched_nco":
        f = _arr(kw["frequencies"], n)
        fr = f.mean() + 0.15 * (f.max() - f.min())
        ql, qc = 8e3, 12e3
        rng = _rng(n, f.sum())
        noise = 1e-4 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
        return 0.02 * np.exp(0.3j) * (1 - (ql / qc) / (1 + 2j * ql * (f - fr) / fr)) + noise
    if function_name == "rabi_sched":
        a = _arr(kw["pulse_amp"], n)
        return _iq((1 - np.cos(np.pi * a / 0.66)) / 2, n, a.sum())
    if function_name == "rabi_amplification":
        a, k = _arr(kw["pulse_amp"], n), _arr(kw["pi_number"], n)
        return _iq(np.sin((k + 1) * np.pi / 2 * a / 0.7) ** 2, n, a.sum(), k.sum())
    if function_name == "ramsey_sched":
        t = _arr(kw["times"], n)
        det = float(np.atleast_1d(kw.get("artificial_detuning", 0.0))[0])
        return _iq(0.5 * (1 - np.cos(2 * np.pi * (det + 40e3) * t) * np.exp(-t / 15e-6)), n, t.sum(), det)
    if function_name in ("t1_sched", "echo_sched"):
        t = _arr(kw["times"], n)
        tau = 25e-6 if function_name == "t1_sched" else 35e-6
        return _iq(np.exp(-t / tau), n, t.sum(), tau)
    if function_name == "multi_qubit_t1_and_t2":
        t = _arr(kw["times"], n)
        case = int(kw.get("case", 1))
        p = np.exp(-t / (20e-6 + 5e-6 * channel)) if case == 1 else \
            0.5 * (1 + np.cos(2 * np.pi * 100e3 * t) * np.exp(-t / (18e-6 + 4e-6 * channel)))
        return _iq(p, n, t.sum(), case, channel)
    if function_name == "allxy_sched":
        pattern = np.array([0] * 5 + [0.5] * 12 + [1] * 4, dtype=float)
        return _iq(np.resize(np.repeat(pattern, max(1, n // pattern.size)), n), n, 21)
    if function_name == "randomized_benchmarking_schedule":
        lengths = _arr(kw["lengths"], n)
        seed = float(np.atleast_1d(kw.get("seeds", 0))[0])
        # excited population decays from |g> towards 0.5; the last two points of each batch
        # are the |g> and |e> calibration points
        pop = 0.5 - 0.5 * 0.97 ** lengths
        pop[-2:] = [0.0, 1.0]
        return _iq(pop, n, lengths.sum(), seed, noise=5e-4)
    if function_name in ("readout_calibration_sched", "multiplexed_readout_calibration_sched"):
        states = _arr(kw["prepared_states"], n)
        return _iq(states, n, states.sum(), channel, noise=2e-3)
    if function_name in ("iswap_RPE_f", "iswap_RPE_theta_sum"):
        lengths = _arr(kw["lengths"], n)
        return _iq(0.5 * (1 + np.cos(0.4 * lengths + 0.3 * channel)), n, lengths.sum(), channel)
    return _iq(0.5 * (1 + np.cos(0.7 * idx)), n, n, channel)


def simulated_gettable_data(gettable, real_data):
    """Replace a gettable's data: ``[I0, Q0, I1, Q1, ...]`` or magnitude/phase pairs."""
    n = len(np.atleast_1d(real_data[0]))
    channels = len(getattr(gettable, "name", [])) // 2 or 1
    thresholded = len(real_data) == channels  # one array per channel: the state, not I and Q
    out = []
    for ch in range(channels):
        z = simulated_points(gettable.schedule_function.__name__, gettable._evaluated_sched_kwargs, n, ch)
        if thresholded:
            out.append(np.clip(((z - G0) / (E0 - G0)).real, 0, 1))
        elif getattr(gettable, "real_imag", True):
            out.extend([z.real, z.imag])
        else:
            out.extend([np.abs(z), np.angle(z, deg=True)])
    return tuple(out)


def simulated_raw(schedule_name, shape, call_index):
    """Values for a runner's raw acquisitions of the given ``shape`` (old layout)."""
    if schedule_name == "DRAG calibration":  # (2n,) averaged: two lines crossing
        n = shape[0] // 2
        x = np.linspace(-1, 1, n)
        out = np.empty(shape[0], dtype=complex)
        out[0::2] = _iq(0.5 + 0.3 * (x - 0.2), n, 1)
        out[1::2] = _iq(0.5 - 0.3 * (x - 0.2), n, 2)
        return out
    if schedule_name == "Readout weight optimization":  # (1, samples) trace, g then e
        t = np.arange(shape[-1]) * 1e-9
        level = G0 if call_index % 2 == 0 else E0
        envelope = 1 - np.exp(-t / 300e-9)
        return (level * envelope * np.exp(2j * np.pi * 45e6 * t)).reshape(shape)
    reps, cols = shape  # (repetition, 2n) single shots, g/e interleaved per setpoint
    rng = _rng(reps, cols, call_index)
    snr = np.exp(-((np.arange(cols // 2) - 0.6 * cols / 2) / (cols / 6)) ** 2)
    out = np.empty(shape, dtype=complex)
    for i in range(cols // 2):
        sep = 0.3 + 0.7 * snr[i]
        out[:, 2 * i] = G0 + 3e-3 * (rng.standard_normal(reps) + 1j * rng.standard_normal(reps))
        out[:, 2 * i + 1] = G0 + sep * (E0 - G0) + 3e-3 * (rng.standard_normal(reps) + 1j * rng.standard_normal(reps))
    return out


def _with_simulated_values(dataset, schedule_name, counter):
    counter[schedule_name] = counter.get(schedule_name, -1) + 1
    for label in list(dataset.data_vars):
        data = dataset[label]
        # the shape the coordinates describe (the dummy cluster may return empty traces)
        shape = tuple(dataset.sizes[d] for d in data.dims)
        values = simulated_raw(schedule_name, shape, counter[schedule_name])
        dataset = dataset.drop_vars(label)
        dataset[label] = (data.dims, values, dict(data.attrs))
    return dataset


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------
def _num(x):
    x = np.asarray(x)
    if np.iscomplexobj(x):
        return {"re": _num(x.real), "im": _num(x.imag)}
    if x.dtype.kind in "fiub":
        return np.round(x.astype(float), 12).tolist()
    return [str(v) for v in x.ravel().tolist()]


def _jsonable(value):
    if isinstance(value, (list, tuple, np.ndarray)) and len(value) == 0:
        return None  # an unset weight: [] in quantify-scheduler, None in qblox-scheduler
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    if isinstance(value, np.ndarray):
        return _num(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return None if value is None else str(value)


def summarize_dataset(ds):
    attrs = {k: _jsonable(v) for k, v in ds.attrs.items() if k not in ("tuid",)}
    variables = {}
    for name in list(ds.coords) + list(ds.data_vars):
        v = ds[name]
        variables[str(name)] = {
            "dims": [str(d) for d in v.dims],
            "attrs": {k: _jsonable(v.attrs.get(k)) for k in ("name", "long_name", "units") if k in v.attrs},
            "values": _num(v.values),
        }
    return {"attrs": attrs, "variables": variables}


def _run_case(nodes, env, method, make_kwargs, device_state, load_dataset):
    entry = {}
    try:
        ok, value = getattr(nodes, method)(**make_kwargs(env))
        entry.update(status="ok", ok=bool(ok), value=_jsonable(value))
    except Exception as exc:  # noqa: BLE001  recorded and compared
        entry.update(status="error", error=f"{type(exc).__name__}: {exc}",
                     traceback=traceback.format_exc(limit=-4))
    entry["device"] = device_state(env)
    tuids = nodes.history[-1]["tuids"] if nodes.history else []
    entry["datasets"] = [summarize_dataset(load_dataset(t)) for t in tuids]
    return entry


def _load_tool(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# qqea side (quantify-scheduler stack)
# --------------------------------------------------------------------------
def dump_qqea(qqea, snapshot, only):
    sys.path.insert(0, os.path.join(qqea, "src"))
    import quantify_scheduler.gettables as qs_gettables
    from qcodes.instrument import Instrument
    from quantify_core.data import handling as dh
    from quantify_core.measurement import MeasurementControl
    from quantify_scheduler.instrument_coordinator import InstrumentCoordinator
    from quantify_scheduler.instrument_coordinator.components.qblox import ClusterComponent

    import qqea.experiments.runners as runners
    from qqea.experiments import dry_run
    from qqea.experiments.calibration_nodes import CalibrationNodes

    tool = _load_tool(os.path.join(qqea, "tools", "compare_schedules.py"), "qqea_compare")
    with open(snapshot) as f:
        hardware_cfg = json.load(f)["instruments"]["quantum_device"]["parameters"]["hardware_config"]["value"]

    original_get, original_run = qs_gettables.ScheduleGettable.get, runners.run_compiled
    counter = {}

    def get(self):
        return simulated_gettable_data(self, original_get(self))

    def run_compiled(schedule, quantum_device, instrument_coordinator, timeout_sec):
        try:
            raw = original_run(schedule, quantum_device, instrument_coordinator, timeout_sec)
        except ValueError as exc:
            # qblox-instruments 0.16's dummy cluster returns an empty scope trace, which
            # quantify-scheduler rejects; use its Trace layout, (acq_index, trace_index)
            if schedule.name != "Readout weight optimization" or "trace_index_0" not in str(exc):
                raise
            import re

            import xarray as xr
            samples = int(re.search(r"length (\d+) on coordinate", str(exc)).group(1))
            raw = xr.Dataset({0: (("acq_index_0", "trace_index_0"), np.zeros((1, samples), complex))},
                             coords={"acq_index_0": [0], "trace_index_0": np.arange(samples)})
        return _with_simulated_values(raw, schedule.name, counter)

    def device_state(env):
        out = {}
        for q in env["pair"]:
            for sub, p in ELEMENT_PARAMS:
                if p == "beta":
                    value = getattr(q, sub).motzoi() * getattr(q, sub).duration() / 8
                else:
                    value = getattr(q, sub).parameters[p]()
                    if isinstance(value, str):
                        value = json.loads(value) if value.strip().startswith("[") else value
                out[f"{q.name}.{sub}.{p}"] = _jsonable(value if not (isinstance(value, list) and not value) else None)
        edge = env["qd"].get_edge("qubit1_qubit2")
        for p in ("ac_stark_phase_q1", "ac_stark_phase_q2"):
            out[f"qubit1_qubit2.iswap.{p}"] = float(edge.iswap.parameters[p]())
        return out

    qs_gettables.ScheduleGettable.get = get
    runners.run_compiled = run_compiled
    results = {}
    try:
        for name, method, make_kwargs in CASES:
            if only and not any(o in name for o in only):
                continue
            Instrument.close_all()
            counter.clear()
            dh.set_datadir(tempfile.mkdtemp(prefix="qqea_nodes_"))
            cluster = dry_run.dummy_cluster(hardware_cfg)
            ic = InstrumentCoordinator("ic")
            ic.add_component(ClusterComponent(cluster))
            meas_ctrl = MeasurementControl("meas_ctrl")
            meas_ctrl.verbose(False)
            qd, q1, q2 = tool.build_device(snapshot)
            qd.hardware_config(hardware_cfg)
            qd.instr_instrument_coordinator(ic.name)
            nodes = CalibrationNodes(qd, meas_ctrl, ACQ_DELAY, instrument_coordinator=ic)
            env = {"q1": q1, "q2": q2, "pair": [q1, q2], "qd": qd, "q1_ro": q1.clock_freqs.readout()}
            results[name] = _run_case(nodes, env, method, make_kwargs, device_state, dh.load_dataset)
            print(f"  {name}: {results[name]['status']}", flush=True)
    finally:
        qs_gettables.ScheduleGettable.get = original_get
        runners.run_compiled = original_run
        Instrument.close_all()
    return results


# --------------------------------------------------------------------------
# qsea side (qblox-scheduler stack)
# --------------------------------------------------------------------------
def dump_qsea(only):
    from qcodes.instrument import Instrument
    from quantify_core.data import handling as dh
    from quantify_core.measurement import MeasurementControl

    import qsea.experiments.gettable as gettable_module
    import qsea.experiments.runners as runners
    from qsea.experiments import dry_run
    from qsea.experiments.calibration_nodes import CalibrationNodes
    from qsea.experiments.datadir import set_datadir
    from qsea.schedules import twpa

    original_get, original_run = gettable_module.ScheduleGettable.get, runners.run_schedule
    counter = {}

    def get(self):
        return simulated_gettable_data(self, original_get(self))

    def run_schedule(schedule, agent, timeout=60):
        return _with_simulated_values(original_run(schedule, agent, timeout), schedule.name, counter)

    def device_state(env):
        out = {}
        for q in env["pair"]:
            for sub, p in ELEMENT_PARAMS:
                out[f"{q.name}.{sub}.{p}"] = _jsonable(getattr(getattr(q, sub), p))
        edge = env["qd"].get_edge("qubit1_qubit2")
        for p in ("ac_stark_phase_q1", "ac_stark_phase_q2"):
            out[f"qubit1_qubit2.iswap.{p}"] = float(getattr(edge.iswap, p))
        return out

    gettable_module.ScheduleGettable.get = get
    runners.run_schedule = run_schedule
    results = {}
    try:
        for name, method, make_kwargs in CASES:
            if only and not any(o in name for o in only):
                continue
            Instrument.close_all()
            counter.clear()
            twpa._TWPA_PUMP.clear()
            set_datadir(tempfile.mkdtemp(prefix="qsea_nodes_"))
            agent = dry_run.dummy_agent()
            meas_ctrl = MeasurementControl("meas_ctrl")
            meas_ctrl.verbose(False)
            nodes = CalibrationNodes(agent, meas_ctrl, ACQ_DELAY)
            qd = agent.quantum_device
            q1, q2 = qd.get_element("qubit1"), qd.get_element("qubit2")
            env = {"q1": q1, "q2": q2, "pair": [q1, q2], "qd": qd, "q1_ro": q1.clock_freqs.readout}
            results[name] = _run_case(nodes, env, method, make_kwargs, device_state, dh.load_dataset)
            print(f"  {name}: {results[name]['status']}", flush=True)
    finally:
        gettable_module.ScheduleGettable.get = original_get
        runners.run_schedule = original_run
        Instrument.close_all()
    return results


# --------------------------------------------------------------------------
# Compare
# --------------------------------------------------------------------------
def _close(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}/{k}: only in {'reference' if k in a else 'qsea'}")
            else:
                out += _close(a[k], b[k], f"{path}/{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: {len(a)} vs {len(b)} entries"]
        if a and all(isinstance(x, (int, float)) or x is None for x in a + b):
            x = np.array([np.nan if v is None else v for v in a], dtype=float)
            y = np.array([np.nan if v is None else v for v in b], dtype=float)
            if np.allclose(x, y, rtol=1e-6, atol=1e-12, equal_nan=True):
                return []
            i = int(np.nanargmax(np.abs(x - y))) if np.isfinite(x - y).any() else 0
            return [f"{path}: differs, e.g. [{i}] {x[i]!r} vs {y[i]!r}"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += _close(x, y, f"{path}[{i}]")
        return out
    if isinstance(a, float) and isinstance(b, float):
        return [] if np.isclose(a, b, rtol=1e-6, atol=1e-12, equal_nan=True) else [f"{path}: {a!r} vs {b!r}"]
    return [] if a == b else [f"{path}: {str(a)[:80]} vs {str(b)[:80]}"]


def _drag_value(entry, duration):
    # qqea returns and saves motzoi, qsea beta = motzoi * duration / 8
    entry = json.loads(json.dumps(entry))
    if isinstance(entry.get("value"), float):
        entry["value"] = entry["value"] * duration / 8
    for ds in entry["datasets"]:
        if "motzoi_list" in ds["attrs"]:
            ds["attrs"]["beta_list"] = [m * duration / 8 for m in ds["attrs"].pop("motzoi_list")]
    return entry


def compare(ref, new, limit=10):
    report, counts = [], {"same": 0, "different": 0, "error": 0}
    for name, n in new.items():
        b = ref.get(name)
        if b is None:
            report.append(f"NEW        {name}")
            continue
        if name == "drag_calibration":
            b = _drag_value(b, n["device"]["qubit1.rxy.duration"])
        problems = []
        for key in ("status", "ok", "value", "error"):
            if key in b or key in n:
                problems += _close(b.get(key), n.get(key), key)
        problems += _close(b["device"], n["device"], "device")
        problems += _close(b["datasets"], n["datasets"], "datasets")
        if n["status"] == "error" and b["status"] != "error":
            problems.append(n["traceback"])
        if problems:
            report.append(f"DIFFERENT  {name}")
            report += ["    " + p for p in problems[:limit]]
            counts["different" if n["status"] == b["status"] else "error"] += 1
        else:
            report.append(f"same       {name}: ok={n.get('ok')}, {len(n['datasets'])} dataset(s)")
            counts["same"] += 1
    report.append("\n" + ", ".join(f"{v} {k}" for k, v in counts.items()))
    return "\n".join(report), counts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd")
    d = sub.add_parser("dump-qqea", help="write the reference from qqea (qblox_env stack)")
    d.add_argument("--qqea", required=True)
    d.add_argument("--snapshot", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--only", default="")
    parser.add_argument("--only", default="")
    parser.add_argument("--reference", default=REFERENCE)
    args = parser.parse_args()
    only = [o for o in args.only.split(",") if o]
    if args.cmd == "dump-qqea":
        with open(args.out, "w") as f:
            json.dump(dump_qqea(args.qqea, args.snapshot, only), f)
        return
    with open(args.reference) as f:
        ref = json.load(f)
    report, counts = compare(ref, dump_qsea(only))
    print(report)
    sys.exit(1 if counts["different"] or counts["error"] else 0)


if __name__ == "__main__":
    main()
