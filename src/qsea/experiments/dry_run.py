"""Dry runs: exercise the calibration nodes on a dummy Qblox cluster.

Never against the live setup. In a dry run the schedules are compiled and uploaded
to a qblox-instruments dummy cluster, so compilation, ``meas_ctrl`` and the analysis
all run; only the acquired data is fake. Example::

    from qsea.experiments import dry_run

    agent = dry_run.dummy_agent()                      # instead of make_agent(cluster_ip=...)
    nodes = CalibrationNodes(agent, meas_ctrl, ACQ_DELAY)

    with dry_run.simulate(dry_run.readout_data()):
        ok, fid = nodes.readout_calibration(agent.quantum_device.get_element("qubit1"))

Without :func:`simulate` the dummy cluster returns empty data, which still
checks that every node compiles, runs, and fails cleanly with ``(False, None)``.
"""

import contextlib

import numpy as np

from qsea.experiments.simulated_data import (
    ErrorModel,
    get_simulated_rb_data,
    get_simulated_readout_data,
    gate_strings_from_schedule,
)

def dummy_agent(device=None, hardware_config=None, **kwargs):
    """A ``HardwareAgent`` on a qblox-instruments dummy cluster with the modules of the
    hardware config (defaults: the lab configs). See :func:`qsea.experiments.agent.make_agent`."""
    from qsea.experiments.agent import make_agent

    return make_agent(device, hardware_config, dummy=True, **kwargs)


@contextlib.contextmanager
def simulate(data_function):
    """Replace ``ScheduleGettable.get`` data with ``data_function(gettable, real_data)``.

    The real ``get`` still runs first (on the dummy cluster), so compilation
    and upload are exercised; ``data_function`` returns ``[I0, Q0, I1, Q1, ...]``
    and is converted to magnitude/phase (degrees) when the gettable was made
    with ``real_imag=False``. The original ``get`` is restored on exit.
    """
    from qsea.experiments.gettable import ScheduleGettable

    original_get = ScheduleGettable.get

    def get(self):
        data = data_function(self, original_get(self))
        if getattr(self, "real_imag", True):
            return tuple(data)
        out = []
        for i_data, q_data in zip(data[0::2], data[1::2]):
            z = np.asarray(i_data) + 1j * np.asarray(q_data)
            out.extend([np.abs(z), np.angle(z, deg=True)])
        return tuple(out)

    ScheduleGettable.get = get
    try:
        yield
    finally:
        ScheduleGettable.get = original_get


def readout_data(states_key="prepared_states", **blob_kwargs):
    """Data function for the readout calibration nodes: one IQ blob per prepared state.

    ``blob_kwargs`` go to :func:`get_simulated_readout_data` (centroids, noise).
    For ``multiplexed_readout_calibration`` every channel gets the same blobs.
    """
    def data_function(gettable, real_data):
        states = np.asarray(gettable.schedule_kwargs[states_key]())
        num_channels = (getattr(gettable, "num_channels", None)
                        or getattr(gettable, "_num_channels", None) or 1)
        data = []
        for _ in range(num_channels):
            data.extend(get_simulated_readout_data(states, **blob_kwargs))
        return data

    return data_function


def rb_data(error_model=None, num_cal_points=0):
    """Data function for ``randomized_benchmarking``, from the compiled gate sequence.

    ``num_cal_points`` = 0 matches ``randomized_benchmarking_schedule``, which
    has no calibration points; check this if that schedule changes.
    """
    error_model = error_model or ErrorModel(depolarizing_error=0.002)

    def data_function(gettable, real_data):
        compiled = gettable.compiled_schedule
        return get_simulated_rb_data(
            error_model=error_model,
            gate_strings=gate_strings_from_schedule(compiled),
            lengths=np.asarray(gettable.schedule_kwargs["lengths"]()),
            repetitions=compiled.repetitions,
            num_cal_points=num_cal_points,
        )

    return data_function
