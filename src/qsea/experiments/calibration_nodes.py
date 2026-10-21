"""Calibration nodes extracted from the SNL315 notebook.

Each measurement/calibration routine ("node") is a method of
:class:`CalibrationNodes`. The shared runtime instruments (the qblox-scheduler
``HardwareAgent`` and ``meas_ctrl``) and constants (``ACQ_DELAY``) are held on the
instance, so the notebook only needs to construct the object once::

    from quantify_core.measurement import MeasurementControl
    from qsea.experiments.agent import make_agent
    from qsea.experiments.calibration_nodes import CalibrationNodes

    agent = make_agent()                      # configs/ + QBLOX_CLUSTER_IP
    meas_ctrl = MeasurementControl("meas_ctrl")
    nodes = CalibrationNodes(agent, meas_ctrl, ACQ_DELAY)
    qubit1 = agent.quantum_device.get_element("qubit1")
    ok, fr = nodes.resonator_calibration(qubit1, amp=..., duration=...)

Sweeps run through ``meas_ctrl`` with :class:`qsea.experiments.gettable.ScheduleGettable`
on the agent, so the datasets are the same as qqea's. ``drag_calibration`` and the
``ro_*_optimization``/``ro_weight_calibration`` nodes run on the agent directly.

The ``qubit`` object stays a per-call argument since it changes between nodes.

Every node returns ``(ok, value)`` and does not raise on a bad fit. Each call
is also appended to ``nodes.history`` (time, node, qubits, ok, value, and the
TUIDs of the datasets it wrote).

The methods are grouped by topic in :mod:`qsea.experiments.nodes`:
``single_qubit``, ``readout``, ``iswap_stark`` and ``roadmap``.
"""

from qsea.experiments.nodes.iswap_stark import IswapStarkNodes
from qsea.experiments.nodes.readout import ReadoutNodes
from qsea.experiments.nodes.roadmap import RoadmapNodes
from qsea.experiments.nodes.single_qubit import SingleQubitNodes

__all__ = ["CalibrationNodes"]


class CalibrationNodes(SingleQubitNodes, ReadoutNodes, IswapStarkNodes, RoadmapNodes):
    """Container for calibration nodes sharing the same runtime instruments.

    Parameters
    ----------
    agent : HardwareAgent
        From :func:`qsea.experiments.agent.make_agent`; ``agent.quantum_device`` is the
        device the nodes read and update.
    meas_ctrl : MeasurementControl
    acq_delay : float
        Acquisition delay (time of flight) in seconds, used by resonator spectroscopy.
    """
