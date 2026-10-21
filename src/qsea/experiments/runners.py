"""Hardware runners: build a schedule, run it on the ``HardwareAgent`` and return the raw
acquisitions, in the layout quantify-scheduler's ``InstrumentCoordinator.retrieve_acquisition()``
had, which the fits in :mod:`qsea.fitting.readout` and ``DRAG_fit`` read.
These bypass ``meas_ctrl``/``ScheduleGettable`` because the fits need the raw
complex acquisitions (single shots, Trace). Readouts go through
:func:`qsea.schedules.twpa.measure_with_twpa`, so each qubit's TWPA setting
decides whether the pump is gated on. Each runner is split into a ``*_schedule`` builder,
which only builds the schedule, and the run function.
``CalibrationNodes`` saves what these return with
:func:`qsea.experiments.saving.save_retrieve_acquisition_dataset`; calling a
runner directly saves nothing, as before. For an ad hoc schedule, :func:`run_and_save` runs and
saves in one go.

Changes from qqea: the run functions take the ``HardwareAgent`` instead of
``instrument_coordinator`` and ``quantum_device``; the DRAG runner sweeps ``rxy.beta``
(``beta_list``) instead of ``motzoi`` (see :func:`qsea.device.drag_beta_from_motzoi`).
"""

from typing import Union

import numpy as np
import xarray as xr
from qblox_scheduler.operations.gate_library import Reset, Rxy, X
from qblox_scheduler.operations.pulse_library import IdlePulse, SetClockFrequency
from qblox_scheduler.schedules.schedule import TimeableSchedule

from qsea.schedules.twpa import measure_with_twpa

__all__ = [
    "readout_freq_optimization_schedule",
    "readout_amp_optimization_schedule",
    "readout_len_optimization_schedule",
    "readout_weight_optimization_schedule",
    "drag_calibration_schedule",
    "legacy_acquisition_layout",
    "run_schedule",
    "run_and_save",
    "readout_freq_optimization",
    "readout_amp_optimization",
    "readout_len_optimization",
    "readout_weight_optimization",
    "DRAG_calibration_sched",
]


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def _as_1d(values) -> np.ndarray:
    """``values`` as a 1-D array; a scalar becomes a one-element array."""
    arr = np.asarray(values)
    return arr.reshape(arr.shape or (1,))


def legacy_acquisition_layout(dataset: xr.Dataset) -> xr.Dataset:
    """``HardwareAgent.run`` acquisitions in quantify-scheduler's ``retrieve_acquisition()`` layout.

    ``HardwareAgent`` returns single shots flat along ``acq_index_<label>``, with ``acq_index``
    and ``repetition`` coordinates; quantify-scheduler returned them as a
    ``(repetition, acq_index_<label>)`` array. Averaged bins and traces already have the old
    shape and only lose those extra coordinates. Data variables keep their acquisition label
    as name.
    """
    out = xr.Dataset(attrs=dict(dataset.attrs))
    for label, data in dataset.data_vars.items():
        dim = data.attrs.get("acq_index_dim_name", data.dims[0])
        if "repetition" not in data.coords or data.ndim != 1:
            # drop qblox-scheduler's extra coordinates (acq_index, ...); keep the dimensions'
            out[label] = data.drop_vars([c for c in data.coords if c not in data.dims])
            continue
        reps = data["repetition"].values.astype(int)
        index = (data["acq_index"].values if "acq_index" in data.coords
                 else np.arange(data.sizes[dim])).astype(int)
        rep_values, index_values = np.unique(reps), np.unique(index)
        values = np.full((rep_values.size, index_values.size), np.nan, dtype=data.dtype)
        values[np.searchsorted(rep_values, reps), np.searchsorted(index_values, index)] = data.values
        out[label] = xr.DataArray(
            values, dims=("repetition", dim), coords={dim: index_values}, attrs=dict(data.attrs),
        )
    return out


def run_schedule(schedule, agent, timeout=60):
    """Run ``schedule`` on ``agent`` and return the acquisitions in the old layout."""
    raw = agent.run(schedule, timeout=timeout, save_to_experiment=False, save_snapshot=False)
    return legacy_acquisition_layout(raw)


def run_and_save(agent, schedule, name=None, timeout=60) -> xr.Dataset:
    """Run ``schedule`` on ``agent`` and save the dataset like ``MeasurementControl`` would.

    ``HardwareAgent.run`` would save to ``<date>/<TUID>/`` with no name and a snapshot without
    the device or instrument settings. This saves to ``<date>/<TUID>-<name>/`` (``name``
    defaults to the schedule's) with the full qcodes snapshot: the clusters, external
    instruments and the device (the :class:`qsea.experiments.agent.DeviceSnapshot` and
    ``ElementSnapshot`` instruments of :func:`~qsea.experiments.agent.make_agent`), so
    quantify-core's ``load_dataset``, ``load_snapshot`` and ``get_latest_tuid(contains=name)``
    find it. Returns the dataset as ``HardwareAgent.run`` returned it, with ``tuid`` and
    ``name`` added to its attributes.
    """
    from qsea.experiments.saving import save_retrieve_acquisition_dataset

    name = name or schedule.name
    dataset = agent.run(schedule, timeout=timeout, save_to_experiment=False, save_snapshot=False)
    dataset.attrs["tuid"] = save_retrieve_acquisition_dataset(dataset, name)
    dataset.attrs["name"] = name
    return dataset


def _add_ge_pair(schedule, qubit_name, acq_index, readout_duration, **measure_kwargs):
    """Measure the qubit in |g> (acq_index) and then in |e> (acq_index + 1), one value per
    shot, with the TWPA pump gated on if the qubit's TWPA setting allows."""
    for excited in (False, True):
        schedule.add(Reset(qubit_name))
        if excited:
            schedule.add(X(qubit=qubit_name))
        measure_with_twpa(
            schedule,
            qubit_name,
            readout_duration=readout_duration,
            marker_label=f"TWPA_mark {acq_index + excited}",
            coords={"acq_index": acq_index + excited},
            acq_protocol="IQIntegration",
            average_segment_repetitions=False,
            **measure_kwargs,
        )


# ----------------------------------------------------------------------------
# schedule builders
# ----------------------------------------------------------------------------
def readout_freq_optimization_schedule(qubit, frequencies, repetitions=1) -> TimeableSchedule:
    """|g>/|e> readout pairs, one per readout frequency (acq_index 2i and 2i+1)."""
    readout_duration = qubit.measure.pulse_duration
    name = qubit.name
    schedule = TimeableSchedule("Readout frequency optimization", repetitions)
    for i, freq in enumerate(_as_1d(frequencies)):
        schedule.add(SetClockFrequency(clock=f"{name}.ro", frequency=freq))
        _add_ge_pair(schedule, name, 2 * i, readout_duration)
    schedule.add(IdlePulse(duration=4e-9), label="end")
    return schedule


def readout_amp_optimization_schedule(qubit, amps, repetitions=1) -> TimeableSchedule:
    """|g>/|e> readout pairs, one per readout pulse amplitude."""
    readout_duration = qubit.measure.pulse_duration
    name = qubit.name
    schedule = TimeableSchedule("Readout amplitude optimization", repetitions)
    for i, amp in enumerate(_as_1d(amps)):
        _add_ge_pair(schedule, name, 2 * i, readout_duration, pulse_amp=amp)
    schedule.add(IdlePulse(duration=4e-9), label="end")
    return schedule


def readout_len_optimization_schedule(qubit, lens, repetitions=1) -> TimeableSchedule:
    """|g>/|e> readout pairs, one per readout duration (pulse and integration together)."""
    name = qubit.name
    schedule = TimeableSchedule("Readout length optimization", repetitions)
    for i, length in enumerate(_as_1d(lens)):
        _add_ge_pair(
            schedule, name, 2 * i, length,
            pulse_duration=length, integration_time=length,
        )
    schedule.add(IdlePulse(duration=4e-9), label="end")
    return schedule


def readout_weight_optimization_schedule(qubit, excited, repetitions=1) -> TimeableSchedule:
    """One averaged Trace acquisition of the qubit in |g> (or |e> if ``excited``)."""
    name = qubit.name
    schedule = TimeableSchedule("Readout weight optimization", repetitions)
    schedule.add(Reset(name))
    if excited:
        schedule.add(X(qubit=name))
    measure_with_twpa(
        schedule, name, readout_duration=qubit.measure.pulse_duration,
        acq_label=0, acq_protocol="Trace",
    )
    schedule.add(IdlePulse(duration=4e-9), label="end")
    return schedule


# The two AllXY elements DRAG_fit compares: equally sensitive to the DRAG
# phase error, with opposite sign.
_DRAG_PAIRS = (
    ((180, 0), (90, 90)),
    ((180, 90), (90, 0)),
)


def drag_calibration_schedule(qubit, beta_list, repetitions=1) -> TimeableSchedule:
    """For each ``rxy.beta``, the two DRAG-sensitive AllXY elements (acq_index 2i and 2i+1)."""
    readout_duration = qubit.measure.pulse_duration
    name = qubit.name
    schedule = TimeableSchedule("DRAG calibration", repetitions)
    for i, beta in enumerate(_as_1d(beta_list)):
        for k, ((th0, phi0), (th1, phi1)) in enumerate(_DRAG_PAIRS):
            schedule.add(Reset(name))
            schedule.add(Rxy(qubit=name, theta=th0, phi=phi0, beta=beta))
            schedule.add(Rxy(qubit=name, theta=th1, phi=phi1, beta=beta))
            measure_with_twpa(schedule, name, readout_duration=readout_duration,
                              marker_label=f"TWPA_mark {2 * i + k}",
                              coords={"acq_index": 2 * i + k})
    schedule.add(IdlePulse(duration=4e-9), label="end")
    return schedule


# ----------------------------------------------------------------------------
# runners
# ----------------------------------------------------------------------------
def readout_freq_optimization(qubit, frequencies: Union[np.ndarray, float], agent, repetitions: int = 1):
    schedule = readout_freq_optimization_schedule(qubit, frequencies, repetitions)
    return run_schedule(schedule, agent, timeout=90)


def readout_amp_optimization(qubit, amps: Union[np.ndarray, float], agent, repetitions: int = 1):
    schedule = readout_amp_optimization_schedule(qubit, amps, repetitions)
    return run_schedule(schedule, agent, timeout=90)


def readout_len_optimization(qubit, lens: Union[np.ndarray, float], agent, repetitions: int = 1):
    schedule = readout_len_optimization_schedule(qubit, lens, repetitions)
    return run_schedule(schedule, agent, timeout=90)


def readout_weight_optimization(qubit, agent, repetitions: int = 1):
    """Return ``(g_trace, e_trace)``, two separate averaged Trace runs."""
    g_trace, e_trace = (
        run_schedule(readout_weight_optimization_schedule(qubit, excited, repetitions), agent, timeout=30)
        for excited in (False, True)
    )
    return g_trace, e_trace


def DRAG_calibration_sched(qubit, beta_list: Union[np.ndarray, float], agent, repetitions: int = 1):
    schedule = drag_calibration_schedule(qubit, beta_list, repetitions)
    return run_schedule(schedule, agent, timeout=60)
