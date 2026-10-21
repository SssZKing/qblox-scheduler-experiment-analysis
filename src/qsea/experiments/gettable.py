"""``ScheduleGettable`` for qblox-scheduler: quantify-core's ``MeasurementControl`` on a ``HardwareAgent``.

qblox-scheduler dropped ``ScheduleGettable``. This one keeps its interface (constructor
arguments, ``name``/``label``/``unit``, ``batched``, ``get()``), so the calibration nodes and
notebooks keep driving sweeps with ``MeasurementControl`` and get the same datasets as
before. ``get()`` builds the schedule, runs it with ``HardwareAgent.run`` and turns the
acquisitions into ``MeasurementControl``'s arrays with qblox-scheduler's copy of
quantify-core's ``_process_acquired_data``.

::

    gettable = ScheduleGettable(agent, schedule_function=rabi_sched,
                                schedule_kwargs={"pulse_amp": amp, ...}, batched=True)
    meas_ctrl.gettables(gettable)
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

__all__ = ["ScheduleGettable", "evaluate_parameters"]


def evaluate_parameters(kwargs: dict[str, Any]) -> dict[str, Any]:
    """``kwargs`` with every qcodes ``Parameter`` value replaced by its current value."""
    from qcodes.parameters import ParameterBase

    return {k: (v() if isinstance(v, ParameterBase) else v) for k, v in kwargs.items()}


class ScheduleGettable:
    """Run a schedule on a ``HardwareAgent`` and return its acquisitions for ``MeasurementControl``.

    Parameters
    ----------
    agent
        The ``HardwareAgent`` (see :func:`qsea.experiments.agent.make_agent`).
    schedule_function
        Builds the schedule; called with the evaluated ``schedule_kwargs`` and
        ``repetitions=agent.quantum_device.cfg_sched_repetitions``.
    schedule_kwargs
        Keyword arguments of ``schedule_function``. qcodes ``Parameter`` values (the
        ``MeasurementControl`` settables) are evaluated on every ``get()``.
    num_channels, data_labels, real_imag, batched, max_batch_size, always_initialize
        As in quantify-scheduler's ``ScheduleGettable``. ``always_initialize`` is accepted
        and ignored: every ``get()`` builds and compiles the schedule.
    timeout
        Seconds ``HardwareAgent.run`` waits for the cluster.
    """

    def __init__(
        self,
        agent,
        schedule_function: Callable,
        schedule_kwargs: dict[str, Any],
        num_channels: int = 1,
        data_labels: list[str] | None = None,
        real_imag: bool = True,
        batched: bool = False,
        max_batch_size: int = 1024,
        always_initialize: bool = True,  # noqa: ARG002
        timeout: int = 60,
    ) -> None:
        self.agent = agent
        self.quantum_device = agent.quantum_device
        self.schedule_function = schedule_function
        self.schedule_kwargs = schedule_kwargs
        self._evaluated_sched_kwargs: dict[str, Any] = {}
        self.real_imag = real_imag
        self.batched = batched
        self.batch_size = max_batch_size
        self.num_channels = num_channels
        self.timeout = timeout
        self.schedule = None
        self.compiled_schedule = None
        self.raw_data = None
        if real_imag:
            self.name = ["I", "Q"] * num_channels
            self.label = data_labels or [f"Voltage {iq}{ch}" for ch in range(num_channels) for iq in "IQ"]
            self.unit = ["V", "V"] * num_channels
        else:
            self.name = ["magn", "phase"] * num_channels
            self.label = data_labels or [
                f"{val}{ch}" for ch in range(num_channels) for val in ("Magnitude", "Phase")
            ]
            self.unit = ["V", "deg"] * num_channels

    def __call__(self):
        return self.get()

    def initialize(self):
        """Build the schedule from the current settable values."""
        self._evaluated_sched_kwargs = evaluate_parameters(self.schedule_kwargs)
        self.schedule = self.schedule_function(
            **self._evaluated_sched_kwargs,
            repetitions=self.quantum_device.cfg_sched_repetitions,
        )
        return self.schedule

    def compile(self):
        """Build and compile the schedule without running it."""
        self.initialize()
        self.compiled_schedule = self.agent.compile(self.schedule)
        return self.compiled_schedule

    def get(self) -> tuple[np.ndarray, ...]:
        """Build, compile and run the schedule; return the data as ``MeasurementControl`` expects it."""
        from qblox_scheduler.quantify_utils import _process_acquired_data

        self.initialize()
        self.raw_data = self.agent.run(
            self.schedule, timeout=self.timeout, save_to_experiment=False, save_snapshot=False
        )
        self.compiled_schedule = self.agent.latest_compiled_schedule
        if len(self.raw_data.data_vars) == 0:
            raise RuntimeError("HardwareAgent.run returned no acquisitions, but some were expected.")
        return _process_acquired_data(self.raw_data, self.batched, self.real_imag)
