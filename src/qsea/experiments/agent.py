"""The ``HardwareAgent`` that runs schedules on the cluster, set up from ``configs/``.

::

    from qsea.experiments.agent import make_agent
    agent = make_agent(cluster_ip="...")        # or set QBLOX_CLUSTER_IP
    agent = make_agent(dummy=True)              # a qblox-instruments dummy cluster
    device = agent.quantum_device               # the QuantumDevice the nodes update

``make_agent`` also adds qcodes instruments that only exist to be snapshotted, because
qblox-scheduler devices are not qcodes instruments any more and ``MeasurementControl`` would
otherwise save datasets whose snapshot says nothing about the device:

- ``quantum_device`` (:class:`DeviceSnapshot`): the whole device (elements, edges), the
  hardware config and the TWPA pump settings;
- one per element and edge (``qubit1``, ``qubit1_qubit2``, ... :class:`ElementSnapshot`), in
  the layout qqea's snapshots had (``instruments.qubit1.submodules.clock_freqs.parameters.f01.value``),
  so code that reads values from a dataset snapshot keeps working.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from qcodes.instrument import Instrument

__all__ = ["CONFIGS", "CLUSTER_IP_ENV_VAR", "DeviceSnapshot", "ElementSnapshot", "make_agent"]

CONFIGS = Path(__file__).resolve().parents[3] / "configs"
CLUSTER_IP_ENV_VAR = "QBLOX_CLUSTER_IP"


class DeviceSnapshot(Instrument):
    """A qcodes instrument whose snapshot is a qblox-scheduler ``QuantumDevice``.

    The snapshot has the parameters ``elements``, ``edges``, ``cfg_sched_repetitions`` (like
    qqea's ``quantum_device``), plus ``device`` (the full device, as saved by
    :func:`qsea.device.save_quantum_device`), ``hardware_config`` and ``twpa_pump``
    (:func:`qsea.schedules.twpa.twpa_pump_settings`).
    """

    def __init__(self, quantum_device, hardware_config=None, name: str = "quantum_device") -> None:
        super().__init__(name)
        self.quantum_device = quantum_device
        self.hardware_config = hardware_config

    def snapshot_base(self, update=False, params_to_skip_update=None):  # noqa: ARG002
        from qsea.schedules.twpa import twpa_pump_settings

        device = json.loads(self.quantum_device.to_json())
        values = {
            "elements": list(device.get("elements", {})),
            "edges": list(device.get("edges", {})),
            "cfg_sched_repetitions": device.get("cfg_sched_repetitions"),
            "device": device,
            "hardware_config": self.hardware_config,
            "twpa_pump": twpa_pump_settings(),
        }
        return {
            "name": self.name,
            "__class__": f"{type(self).__module__}.{type(self).__name__}",
            "functions": {},
            "submodules": {},
            "parameters": {k: {"name": k, "value": v} for k, v in values.items()},
        }

    def get_idn(self):
        return {"vendor": "qsea", "model": "DeviceSnapshot", "serial": None, "firmware": None}


class ElementSnapshot(Instrument):
    """A qcodes instrument whose snapshot is a device element or edge, in qqea's layout:
    one submodule per element submodule, one parameter (``{"value": ...}``) per field."""

    def __init__(self, element, name: str | None = None) -> None:
        super().__init__(name or element.name)
        self.element = element

    def snapshot_base(self, update=False, params_to_skip_update=None):  # noqa: ARG002
        data = json.loads(self.element.to_json())
        submodules = {}
        for key, value in data.items():
            if isinstance(value, dict):
                submodules[key] = {
                    "name": f"{self.name}_{key}",
                    "parameters": {p: {"name": p, "value": v} for p, v in value.items() if p != "name"},
                    "submodules": {},
                    "functions": {},
                }
        return {
            "name": self.name,
            "__class__": f"{type(self).__module__}.{type(self).__name__}",
            "functions": {},
            "submodules": submodules,
            "parameters": {k: {"name": k, "value": v} for k, v in data.items() if not isinstance(v, dict)},
        }

    def get_idn(self):
        return {"vendor": "qsea", "model": "ElementSnapshot", "serial": None, "firmware": None}


def _replace_instrument(name):
    try:
        Instrument.find_instrument(name).close()
    except KeyError:
        pass


def _hardware_config_with_ip(hardware_config: dict, cluster_ip: str | None) -> dict:
    if not cluster_ip:
        return hardware_config
    config = json.loads(json.dumps(hardware_config))
    clusters = [k for k, v in config["hardware_description"].items()
                if v.get("instrument_type") == "Cluster"]
    if len(clusters) != 1:
        raise ValueError(f"cluster_ip needs exactly one Cluster in hardware_description, found {clusters}")
    config["hardware_description"][clusters[0]]["ip"] = cluster_ip
    return config


def make_agent(
    device=None,
    hardware_config=None,
    *,
    cluster_ip: str | None = None,
    dummy: bool = False,
    datadir=None,
    snapshot_name: str | None = "quantum_device",
):
    """A ``HardwareAgent`` for the lab device.

    Parameters
    ----------
    device
        ``QuantumDevice``, or a path to its JSON. Defaults to ``configs/quantum_device.json``.
    hardware_config
        Hardware config dict, or a path to its JSON. Defaults to ``configs/hardware_config.json``.
    cluster_ip
        Address of the cluster, added to the hardware config at run time (it is kept out of
        the repo). Defaults to the ``QBLOX_CLUSTER_IP`` environment variable. Not needed with
        ``dummy``.
    dummy
        Use a qblox-instruments dummy cluster with the modules of the hardware config.
    datadir
        Data directory for both qblox-scheduler and quantify-core. Defaults to the current
        quantify-core data directory (``HardwareAgent`` would otherwise reset it).
    snapshot_name
        Name of the :class:`DeviceSnapshot` instrument (None: add no snapshot instruments).
        It and the :class:`ElementSnapshot` instruments replace existing instruments of the
        same name. Elements or edges added to the device later are not snapshotted.
    """
    from qblox_scheduler.qblox.hardware_agent import HardwareAgent

    from qsea.device import load_hardware_config, load_quantum_device
    from qsea.experiments.datadir import get_datadir, set_datadir

    if device is None:
        device = CONFIGS / "quantum_device.json"
    if isinstance(device, (str, Path)):
        device = load_quantum_device(device)
    if hardware_config is None:
        hardware_config = CONFIGS / "hardware_config.json"
    if isinstance(hardware_config, (str, Path)):
        hardware_config = load_hardware_config(hardware_config)

    if datadir is None:
        try:
            datadir = get_datadir()
        except Exception:  # noqa: BLE001  quantify-core has no data directory yet
            datadir = None
    if not dummy:
        cluster_ip = cluster_ip or os.environ.get(CLUSTER_IP_ENV_VAR) or None
    agent = HardwareAgent(
        _hardware_config_with_ip(hardware_config, None if dummy else cluster_ip),
        device,
        output_dir=datadir,
        create_dummy_connections=dummy,
    )
    agent.hardware_config_dict = hardware_config  # as loaded, without the cluster address
    if datadir is not None:
        set_datadir(datadir)
    if snapshot_name:
        _replace_instrument(snapshot_name)
        agent.device_snapshot = DeviceSnapshot(device, hardware_config, name=snapshot_name)
        agent.element_snapshots = []
        for element in list(device.elements.values()) + list(device.edges.values()):
            _replace_instrument(element.name)
            agent.element_snapshots.append(ElementSnapshot(element))
    return agent
