"""TWPA pump triggering for readout.

The TWPA pump is gated by a marker on ``<qubit>:switch``. It has to be on before
the readout pulse reaches the TWPA, so the marker starts ``TWPA_RINGUP`` (plus
``TWPA_DELAY``) before the readout and stays on ``TWPA_TAIL`` after it::

    marker start    = readout start + TWPA_DELAY - TWPA_RINGUP
    marker duration = readout duration + TWPA_RINGUP + TWPA_TAIL

Every schedule builder adds its readout through :func:`measure_with_twpa` (gate
level ``Measure``) or :func:`add_twpa_marker` (pulse level readout), so the timing
lives in one place.

Whether a qubit's readout pumps the TWPA is a per-qubit setting, the element
parameter ``twpa_pump``::

    from qsea.schedules.twpa import set_twpa_pump
    set_twpa_pump(qubit1, True)    # readouts of qubit1 trigger the pump
    set_twpa_pump(qubit2, False)   # qubit2 is read out without it

qblox-scheduler elements are pydantic models that reject unknown fields, so the
setting is kept here, by element name, instead of as an extra element parameter.
A qubit that never had it set pumps the TWPA, as all readouts did before the
setting existed. :func:`twpa_pump_settings` returns the current settings, for
saving them with a dataset snapshot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qblox_scheduler import MarkerPulse, Measure
from qblox_scheduler.schedules.schedule import Schedulable

if TYPE_CHECKING:
    from qblox_scheduler.schedules.schedule import TimeableSchedule

TWPA_DELAY = -36e-9
TWPA_RINGUP = 960e-9
TWPA_TAIL = 40e-9

__all__ = [
    "TWPA_DELAY",
    "TWPA_RINGUP",
    "TWPA_TAIL",
    "set_twpa_pump",
    "twpa_pump_enabled",
    "twpa_pump_settings",
    "max_readout_duration",
    "add_twpa_marker",
    "measure_with_twpa",
    "legacy_measure_kwargs",
]


def legacy_measure_kwargs(kwargs: dict) -> dict:
    """``Measure`` keyword arguments with quantify-scheduler's names translated.

    ``acq_index=i`` becomes ``coords={"acq_index": i}``, ``bin_mode`` becomes
    ``average_segment_repetitions``, ``acq_channel`` becomes ``acq_label`` and old
    ``acq_protocol`` names are mapped (:mod:`qsea.schedules.acquisition`). Without this,
    ``Measure`` would take ``bin_mode="append"`` as a device override and silently average.
    """
    from qsea.schedules.acquisition import acq_protocol_name, average_repetitions

    kwargs = dict(kwargs)
    if "acq_index" in kwargs:
        coords = dict(kwargs.get("coords") or {})
        coords.setdefault("acq_index", kwargs.pop("acq_index"))
        kwargs["coords"] = coords
    if "bin_mode" in kwargs:
        kwargs.setdefault("average_segment_repetitions", average_repetitions(kwargs.pop("bin_mode")))
    if "acq_channel" in kwargs:
        kwargs.setdefault("acq_label", kwargs.pop("acq_channel"))
    if "acq_protocol" in kwargs:
        kwargs["acq_protocol"] = acq_protocol_name(kwargs["acq_protocol"])
    return kwargs


# Element name -> whether its readouts trigger the TWPA pump. Missing means True.
_TWPA_PUMP: dict[str, bool] = {}


def _element_name(element) -> str:
    return element if isinstance(element, str) else element.name


def set_twpa_pump(element, enabled: bool = True) -> None:
    """Set whether readouts of ``element`` (an element or its name) trigger the TWPA pump."""
    _TWPA_PUMP[_element_name(element)] = bool(enabled)


def twpa_pump_enabled(qubit) -> bool:
    """Whether readouts of ``qubit`` (an element or its name) trigger the TWPA pump.

    True unless :func:`set_twpa_pump` turned it off for that element name. A name
    with no element behind it (e.g. a bare port prefix) also counts as pumped.
    """
    return _TWPA_PUMP.get(_element_name(qubit), True)


def twpa_pump_settings() -> dict[str, bool]:
    """The elements whose TWPA setting was changed with :func:`set_twpa_pump`, by name."""
    return dict(_TWPA_PUMP)


def max_readout_duration(qubits) -> float:
    """Longest ``measure.pulse_duration`` of one element or an iterable of them."""
    if hasattr(qubits, "name"):
        qubits = [qubits]
    return max(qubit.measure.pulse_duration for qubit in qubits)


def add_twpa_marker(
    schedule: TimeableSchedule,
    ref_op: Schedulable,
    switch_port: str,
    readout_duration: float,
    *,
    delay: float | None = None,
    ref_pt: str = "start",
    label: str | None = None,
) -> Schedulable:
    """Add the TWPA pump marker for a readout that starts at ``ref_op``.

    Parameters
    ----------
    schedule
        Schedule to add the marker to.
    ref_op
        The readout (``Measure``, readout pulse or acquisition) the pump covers.
    switch_port
        Marker port of the TWPA switch, e.g. ``"qubit1:switch"``.
    readout_duration
        Length of the readout the pump has to cover, in seconds.
    delay
        Pump delay in seconds. Defaults to ``TWPA_DELAY``.
    ref_pt
        Point of ``ref_op`` the readout starts at (default ``"start"``).
    label
        Optional label of the marker.

    Returns
    -------
    Schedulable or None
        The marker, or None if the element behind ``switch_port`` has its TWPA
        pump turned off (:func:`set_twpa_pump`).
    """
    if not twpa_pump_enabled(switch_port.split(":")[0]):
        return None
    if delay is None:
        delay = TWPA_DELAY
    return schedule.add(
        MarkerPulse(
            duration=readout_duration + TWPA_RINGUP + TWPA_TAIL,
            port=switch_port,
        ),
        ref_op=ref_op,
        ref_pt=ref_pt,
        rel_time=delay - TWPA_RINGUP,
        label=label,
    )


def measure_with_twpa(
    schedule: TimeableSchedule,
    *qubits: str,
    readout_duration: float,
    rel_time: float = 0,
    ref_op: Schedulable | str | None = None,
    ref_pt: str | None = None,
    label: str | None = None,
    marker_label: str | None = None,
    **measure_kwargs,
) -> Schedulable:
    """Add ``Measure(*qubits, **measure_kwargs)`` and the TWPA pump marker for it.

    The marker goes on the ``<qubit>:switch`` port of the first measured qubit whose
    TWPA pump is on (:func:`set_twpa_pump`); with none on, no marker is added. It is
    added right after the ``Measure``, so the next operation added without a
    ``ref_op`` follows the marker, as the hand-written blocks this replaces did.

    Parameters
    ----------
    schedule
        Schedule to add the readout to.
    *qubits
        Element names to measure. Multiplexed readout passes several.
    readout_duration
        Readout length the pump covers, normally :func:`max_readout_duration` of the
        measured elements.
    rel_time, ref_op, ref_pt, label
        Passed to ``schedule.add`` for the ``Measure``.
    marker_label
        Optional label of the marker.
    **measure_kwargs
        Passed to ``Measure`` (``coords``, ``acq_protocol``, ``average_segment_repetitions``,
        ...; see :mod:`qsea.schedules.acquisition` for the old ``acq_index``/``bin_mode``).

    Returns
    -------
    Schedulable
        The ``Measure``.
    """
    measure_kwargs = legacy_measure_kwargs(measure_kwargs)
    ro_pulse = schedule.add(
        Measure(*qubits, **measure_kwargs),
        rel_time=rel_time,
        ref_op=ref_op,
        ref_pt=ref_pt,
        label=label,
    )
    pumped = [q for q in qubits if twpa_pump_enabled(q)]
    if pumped:
        add_twpa_marker(
            schedule, ro_pulse, pumped[0] + ":switch", readout_duration, label=marker_label
        )
    return ro_pulse
