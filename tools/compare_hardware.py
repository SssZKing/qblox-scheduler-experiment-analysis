"""Check that qsea compiles to the same cluster instructions as qqea for the lab device.

Builds every case of ``tools/compare_schedules.py`` with the lab device and hardware config,
compiles it to Qblox cluster instructions, and compares what each module and sequencer is
told to do: LO frequencies and attenuations, NCO frequency, mixer and calibration settings,
integration length, threshold and rotation, and the waveform and weight samples. The Q1ASM
programs themselves are not compared (qblox-scheduler wraps them in its repetition loop).

The reference comes from qqea in the ``qblox_env`` stack. Make it with (Python 3.9,
qblox_env pins, qqea checkout with the int32 Clifford hash, see
``tests/schedules/reference/README.md``)::

    python tools/compare_hardware.py dump-qqea --qqea <qqea checkout> --snapshot <snapshot.json> \\
        --out tests/schedules/reference/qqea-4de2850-lab-hardware.json

and compare in ``qbs_env``::

    python tools/compare_hardware.py

Known differences, reported separately instead of failing:

- qblox-scheduler leaves ``mixer_corr_phase_offset_degree``/``mixer_corr_gain_ratio`` unset
  (None) where quantify-scheduler wrote 0.0/1.0; with ``auto_sideband_cal`` on, the cluster
  calibrates them either way.
- An NCO frequency beyond +-500 MHz (a case frequency too far from the lab LO) compiled in
  quantify-scheduler and would only fail when uploaded; qblox-scheduler refuses it at
  compile time. Counted as the same.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import traceback

sys.dont_write_bytecode = True

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFERENCE = os.path.join(REPO, "tests", "schedules", "reference", "qqea-4de2850-lab-hardware.json")
DEVICE = os.path.join(REPO, "configs", "quantum_device.json")
HARDWARE = os.path.join(REPO, "configs", "hardware_config.json")

MODULE_KEYS = ("lo0_freq", "lo1_freq", "out0_att", "out1_att", "in0_att", "in1_att",
               "out0_lo_freq_cal_type_default", "out1_lo_freq_cal_type_default")
SEQUENCER_KEYS = ("channel_name", "nco_en", "modulation_freq", "auto_sideband_cal",
                  "integration_length_acq", "thresholded_acq_threshold", "thresholded_acq_rotation")
MIXER_KEYS = ("mixer_corr_phase_offset_degree", "mixer_corr_gain_ratio")
NCO_LIMIT = 500e6


def _plain(value):
    value = getattr(value, "value", value)  # enums
    if isinstance(value, float):
        return float(f"{value:.10g}")
    return value


def _samples(table):
    out = []
    for entry in (table or {}).values():
        out.append([round(float(x), 9) for x in entry["data"]])
    return sorted(out)


def digest(compiled_schedule):
    """What the cluster is told to do, without the Q1ASM programs."""
    out = {}
    for inst_name, inst in compiled_schedule.compiled_instructions.items():
        if not isinstance(inst, dict):
            continue
        for module_name, module in inst.items():
            if not isinstance(module, dict) or "sequencers" not in module:
                continue
            settings = module["settings"]
            settings = settings if isinstance(settings, dict) else vars(settings)
            sequencers = []
            for seq in module["sequencers"].values():
                seq = seq if isinstance(seq, dict) else vars(seq)
                sequence = seq["sequence"]
                sequencers.append({
                    **{k: _plain(seq.get(k)) for k in SEQUENCER_KEYS},
                    "mixer": {k: _plain(seq.get(k)) for k in MIXER_KEYS},
                    "waveforms": _samples(sequence.get("waveforms")),
                    "weights": _samples(sequence.get("weights")),
                })
            sequencers.sort(key=lambda s: json.dumps({k: v for k, v in s.items() if k != "mixer"}, sort_keys=True))
            out[f"{inst_name}/{module_name}"] = {
                "settings": {k: _plain(settings.get(k)) for k in MODULE_KEYS},
                "sequencers": sequencers,
            }
    return out


def _load_tool(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(cases, build, only):
    """``build`` returns the hardware-compiled schedules of a case, or None to skip it."""
    results = {}
    for name, module, func, make_kwargs, env_extra in cases:
        if only and not any(o in name for o in only):
            continue
        entry = {}
        try:
            compiled = build(module, func, make_kwargs, env_extra)
            if not compiled:
                entry["status"] = "skipped"
            else:
                entry["status"] = "ok"
                entry["digest"] = [digest(c) for c in compiled]
        except Exception as exc:  # noqa: BLE001  recorded and compared
            entry["status"] = "error"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["traceback"] = traceback.format_exc(limit=-3)
        results[name] = entry
        print(f"  {name}: {entry['status']}", flush=True)
    return results


def dump_qqea(qqea, snapshot, only):
    """Reference side: qqea with quantify-scheduler (run in the qblox_env stack)."""
    sys.path.insert(0, os.path.join(qqea, "src"))
    import importlib

    from quantify_scheduler.backends import SerialCompiler
    from quantify_scheduler.schedules.schedule import ScheduleBase

    tool = _load_tool(os.path.join(qqea, "tools", "compare_schedules.py"), "qqea_compare")
    with open(snapshot) as f:
        hardware_config = json.load(f)["instruments"]["quantum_device"]["parameters"]["hardware_config"]["value"]

    def build(module, func, make_kwargs, _):
        from qcodes.instrument import Instrument

        Instrument.close_all()  # quantify-scheduler elements are named qcodes instruments
        qd, q1, q2 = tool.build_device(snapshot)
        qd.hardware_config(hardware_config)
        mod = importlib.import_module(f"qqea.schedules.{module}")
        log = []
        env = {"qd": qd, "q1": q1, "q2": q2, "ic": tool.FakeCoordinator(), "mod": mod,
               "pump": tool.FakeSource("TWPA_pump", log), "snail": tool.FakeSource("snail_drive", log)}
        fn = getattr(mod, func, None) or tool._moved_runner(func)  # runners moved to experiments
        value = fn(**make_kwargs(env))
        compiled = list(env["ic"].compiled)  # builders that compile and prepare themselves
        if isinstance(value, ScheduleBase):
            compiled.append(SerialCompiler(name="hw").compile(value, config=qd.generate_compilation_config()))
        return compiled

    cases = [(*c, None) for c in tool.cases()]
    return _run(cases, build, only)


def dump_qsea(only, device=DEVICE, hardware=HARDWARE):
    """qsea with qblox-scheduler, built from the converted lab configs."""
    import importlib

    from qblox_scheduler.backends import SerialCompiler
    from qblox_scheduler.schedules.schedule import TimeableScheduleBase

    from qsea.device import load_hardware_config, load_quantum_device

    tool = _load_tool(os.path.join(REPO, "tools", "compare_schedules.py"), "qsea_compare")
    hardware_config = load_hardware_config(hardware)
    def build(module, func, make_kwargs, _):
        if func in [c[2] for c in tool.cases() if c[0] in tool.PENDING]:
            return None
        qd = load_quantum_device(device)
        qd.hardware_config = hardware_config
        mod = importlib.import_module(f"qsea.schedules.{module}")
        log = []
        env = {"qd": qd, "q1": qd.get_element("qubit1"), "q2": qd.get_element("qubit2"),
               "ic": tool.FakeCoordinator(), "mod": mod,
               "pump": tool.FakeSource("TWPA_pump", log), "snail": tool.FakeSource("snail_drive", log)}
        env["agent"] = tool.FakeAgent(qd, env["ic"])
        if func in tool.RUNNERS:
            runners = importlib.import_module("qsea.experiments.runners")
            getattr(runners, tool.RUNNERS[func])(**tool._runner_kwargs(make_kwargs(env), env))
            value = None
        else:
            value = getattr(mod, func)(**make_kwargs(env))
        compiled = list(env["ic"].compiled)  # builders that compile and prepare themselves
        if isinstance(value, TimeableScheduleBase):
            compiled.append(SerialCompiler(name="hw").compile(value, config=qd.generate_compilation_config()))
        return compiled

    cases = [(*c, None) for c in tool.cases()]
    return _run(cases, build, only)


def _diff(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}/{k}: only in {'reference' if k in a else 'qsea'}")
            else:
                out += _diff(a[k], b[k], f"{path}/{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: {len(a)} vs {len(b)} entries"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += _diff(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [f"{path}: {str(a)[:80]} vs {str(b)[:80]}"]


def compare(ref, new, limit=8):
    report, counts = [], {"same": 0, "different": 0, "error": 0, "skipped": 0}
    mixer_notes = set()
    for name, n in new.items():
        b = ref.get(name, {"status": "missing"})
        if n["status"] == "skipped" or b["status"] == "skipped":
            report.append(f"skipped    {name}")
            counts["skipped"] += 1
            continue
        if b["status"] == "ok" and n["status"] == "error" and "outside the allowed NCO range" in n["error"]:
            nco = [s["modulation_freq"] for c in b["digest"] for m in c.values() for s in m["sequencers"]]
            if any(f is not None and abs(f) > NCO_LIMIT for f in nco):
                report.append(f"same       {name} (NCO frequency beyond 500 MHz: compiled by qqea, refused by qsea)")
                counts["same"] += 1
                continue
        if b["status"] == "error" or n["status"] == "error":
            if b["status"] == n["status"] == "error":
                report.append(f"same       {name} (fails on both sides: {n['error'][:90]})")
                counts["same"] += 1
            else:
                report.append(f"ERROR      {name}: reference {b.get('error', 'ok')[:90]} / qsea {n.get('error', 'ok')[:90]}")
                counts["error"] += 1
            continue
        problems = []
        for line in _diff(b["digest"], n["digest"]):
            if "/mixer/" in line:
                mixer_notes.add(line.split("]/mixer/")[-1])
            else:
                problems.append("    " + line)
        if problems:
            report.append(f"DIFFERENT  {name}")
            report += problems[:limit]
            counts["different"] += 1
        else:
            report.append(f"same       {name}")
            counts["same"] += 1
    if mixer_notes:
        report.append("\nknown difference (not counted): " + "; ".join(sorted(mixer_notes)))
    report.append("\n" + ", ".join(f"{v} {k}" for k, v in counts.items()))
    return "\n".join(report), counts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd")
    d = sub.add_parser("dump-qqea", help="write the reference from qqea (qblox_env stack)")
    d.add_argument("--qqea", required=True, help="qqea checkout")
    d.add_argument("--snapshot", required=True, help="dataset snapshot.json with the lab device")
    d.add_argument("--out", required=True)
    d.add_argument("--only", default="")
    parser.add_argument("--only", default="", help="comma-separated substrings of case names")
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--device", default=DEVICE)
    parser.add_argument("--hardware", default=HARDWARE)
    args = parser.parse_args()
    only = [o for o in args.only.split(",") if o]

    if args.cmd == "dump-qqea":
        with open(args.out, "w") as f:
            json.dump(dump_qqea(args.qqea, args.snapshot, only), f)
        return

    with open(args.reference) as f:
        ref = json.load(f)
    report, counts = compare(ref, dump_qsea(only, args.device, args.hardware))
    print(report)
    sys.exit(1 if counts["different"] or counts["error"] else 0)


if __name__ == "__main__":
    main()
