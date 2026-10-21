"""Quantum device and hardware configuration: load, save, and convert from qqea.

qblox-scheduler devices are pydantic models saved as JSON. Loading one needs the element
and edge classes registered first (``BasicTransmonElement`` from qblox-applications and
qsea's ``CompositeiSWAPEdge``); :func:`load_quantum_device` takes care of that::

    from qsea.device import load_quantum_device, load_hardware_config
    device = load_quantum_device("configs/quantum_device.json")
    hardware_cfg = load_hardware_config("configs/hardware_config.json")

To carry a qqea (quantify-scheduler) device over, convert the snapshot of a dataset::

    from qsea.device import quantum_device_from_snapshot, hardware_config_from_snapshot
    device = quantum_device_from_snapshot("path/to/snapshot.json")
    hardware_cfg = hardware_config_from_snapshot("path/to/snapshot.json")

What the conversion changes:

- ``rxy.motzoi`` becomes ``rxy.beta = motzoi * sigma`` with ``sigma = duration / 8``.
  quantify-scheduler's DRAG derivative was ``-motzoi * (t - mu) / sigma * G(t)``;
  qblox-scheduler's is ``-beta * (t - mu) / sigma**2 * G(t)``, so this keeps the pulse
  identical (checked sample by sample).
- ``measure.acq_channel`` becomes ``measure.acq_label``; empty acquisition weights become
  ``None``; ``measure.acq_weights_sampling_rate`` and ``rxy.reference_magnitude`` no longer
  exist and are dropped.
- The hardware config's ``config_type`` becomes the bare class name, as
  ``qblox-scheduler migrate-configs`` does; nothing else in it changes.
"""

from __future__ import annotations

import json
import math
import warnings
from pathlib import Path
from typing import Any

__all__ = [
    "DRAG_NR_SIGMA",
    "drag_beta_from_motzoi",
    "register_device_types",
    "load_quantum_device",
    "save_quantum_device",
    "load_hardware_config",
    "save_hardware_config",
    "convert_hardware_config",
    "quantum_device_from_snapshot",
    "hardware_config_from_snapshot",
]

# quantify-scheduler and qblox-scheduler both cut the DRAG Gaussian at 4 sigma on each side
DRAG_NR_SIGMA = 4

# qqea submodule parameter -> qblox-scheduler name, per submodule
_RENAMED = {("measure", "acq_channel"): "acq_label"}
# parameters that no longer exist and carry no information we need
_DROPPED = {("measure", "acq_weights_sampling_rate"), ("rxy", "reference_magnitude"), ("rxy", "motzoi")}


def drag_beta_from_motzoi(motzoi: float, duration: float, nr_sigma: float = DRAG_NR_SIGMA) -> float:
    """qblox-scheduler ``rxy.beta`` (seconds) for a quantify-scheduler ``rxy.motzoi``."""
    return motzoi * duration / (2 * nr_sigma)


def register_device_types() -> None:
    """Import the element and edge classes so device JSON with them can be loaded."""
    import qblox_applications.qblox_scheduler.superconducting.transmon  # noqa: F401

    import qsea.schedules.edges  # noqa: F401


def load_quantum_device(path: str | Path):
    """Load a ``QuantumDevice`` saved with :func:`save_quantum_device`."""
    register_device_types()
    from qblox_scheduler import QuantumDevice

    return QuantumDevice.from_json(Path(path).read_text())


def save_quantum_device(device, path: str | Path) -> None:
    """Save a ``QuantumDevice`` as indented JSON."""
    Path(path).write_text(json.dumps(json.loads(device.to_json()), indent=2) + "\n")


def load_hardware_config(path: str | Path) -> dict:
    """Load a hardware config JSON, converting a quantify-scheduler one if needed."""
    return convert_hardware_config(json.loads(Path(path).read_text()))


def save_hardware_config(config: dict, path: str | Path) -> None:
    """Save a hardware config as indented JSON."""
    Path(path).write_text(json.dumps(config, indent=2) + "\n")


def convert_hardware_config(config: dict) -> dict:
    """A quantify-scheduler hardware config in qblox-scheduler form (``config_type`` only)."""
    config = json.loads(json.dumps(config))  # deep copy; tuples become lists
    config_type = config.get("config_type", "")
    if config_type.startswith(("quantify_scheduler.", "qblox_scheduler.")):
        config["config_type"] = config_type.rsplit(".", 1)[-1]
    return config


def _load_snapshot(snapshot: dict | str | Path) -> dict:
    if not isinstance(snapshot, dict):
        snapshot = json.loads(Path(snapshot).read_text())
    return snapshot.get("instruments", snapshot)


def _value(parameter: dict) -> Any:
    return parameter.get("value") if isinstance(parameter, dict) else parameter


def _weights(value):
    if isinstance(value, str):
        value = json.loads(value) if value.strip() else []
    if value is None or len(value) == 0:
        return None
    import numpy as np

    return np.asarray(value)


def _set_element(element, snap: dict, report: list[str]) -> None:
    subs = snap.get("submodules", {})
    rxy = subs.get("rxy", {}).get("parameters", {})
    for sub_name, sub in subs.items():
        target = getattr(element, sub_name, None)
        if target is None:
            report.append(f"{element.name}.{sub_name}: no such submodule, skipped")
            continue
        fields = type(target).model_fields
        for p_name, p in sub.get("parameters", {}).items():
            if (sub_name, p_name) in _DROPPED:
                continue
            new_name = _RENAMED.get((sub_name, p_name), p_name)
            if new_name not in fields:
                report.append(f"{element.name}.{sub_name}.{p_name}: no such parameter, skipped")
                continue
            value = _value(p)
            if new_name in ("acq_weights_a", "acq_weights_b"):
                value = _weights(value)
            elif value is None:
                continue
            setattr(target, new_name, value)
    if "motzoi" in rxy:
        motzoi, duration = _value(rxy["motzoi"]), element.rxy.duration
        beta = drag_beta_from_motzoi(motzoi, duration)
        element.rxy.beta = 0.0 if math.isnan(beta) else beta


def quantum_device_from_snapshot(snapshot: dict | str | Path, name: str | None = None):
    """Build a qblox-scheduler ``QuantumDevice`` from a qqea dataset snapshot.

    Elements become qblox-applications ``BasicTransmonElement`` s and the iSWAP edge a
    qsea ``CompositeiSWAPEdge``; see the module docstring for what is converted.
    Parameters that cannot be carried over are reported with a warning.
    """
    register_device_types()
    from qblox_applications.qblox_scheduler.superconducting.transmon import BasicTransmonElement
    from qblox_scheduler import QuantumDevice

    from qsea.schedules.edges import CompositeiSWAPEdge

    instruments = _load_snapshot(snapshot)
    qd_params = instruments["quantum_device"]["parameters"]
    device = QuantumDevice(name=name or instruments["quantum_device"].get("name", "quantum_device"))
    for key in ("cfg_sched_repetitions", "keep_original_schedule"):
        if _value(qd_params.get(key)) is not None:
            setattr(device, key, _value(qd_params[key]))

    report: list[str] = []
    for element_name in _value(qd_params["elements"]):
        element = BasicTransmonElement(name=element_name)
        _set_element(element, instruments[element_name], report)
        device.add_element(element)

    for edge_name in _value(qd_params["edges"]):
        snap = instruments[edge_name]
        iswap = snap.get("submodules", {}).get("iswap")
        if iswap is None:
            report.append(f"{edge_name}: not an iSWAP edge, skipped")
            continue
        parent, child = edge_name.split("_", 1)
        edge = CompositeiSWAPEdge(parent_element_name=parent, child_element_name=child)
        for p_name, p in iswap.get("parameters", {}).items():
            if p_name in type(edge.iswap).model_fields and _value(p) is not None:
                setattr(edge.iswap, p_name, _value(p))
            else:
                report.append(f"{edge_name}.iswap.{p_name}: no such parameter, skipped")
        device.add_edge(edge)

    if report:
        warnings.warn("Not carried over from the snapshot:\n  " + "\n  ".join(report), stacklevel=2)
    return device


def hardware_config_from_snapshot(snapshot: dict | str | Path) -> dict:
    """The hardware config stored in a qqea dataset snapshot, in qblox-scheduler form."""
    instruments = _load_snapshot(snapshot)
    return convert_hardware_config(_value(instruments["quantum_device"]["parameters"]["hardware_config"]))
