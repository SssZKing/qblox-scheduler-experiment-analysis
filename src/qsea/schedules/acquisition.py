"""Acquisition arguments that changed from quantify-scheduler to qblox-scheduler.

The schedule builders still take the old ``acq_protocol`` names and ``bin_mode``
values, so notebooks written for qqea keep working; these helpers translate them:

- ``acq_protocol``: ``ThresholdedAcquisition`` is now ``ThresholdedIQIntegration``,
  ``SSBIntegrationComplex`` is now ``IQIntegration`` (still accepted by qblox-scheduler).
- ``bin_mode``: gone. ``"average"`` is ``average_segment_repetitions=True`` and
  ``"append"`` (one value per shot) is ``average_segment_repetitions=False``.
- ``acq_index``: gone; bins follow the order of the acquisitions. The builders put the
  old index in ``coords={"acq_index": i}``, so acquisitions that shared an index are
  still averaged together (``HardwareAgent.run`` averages acquisitions with equal coords).
"""

from __future__ import annotations

__all__ = ["LEGACY_ACQ_PROTOCOLS", "acq_protocol_name", "average_repetitions"]

LEGACY_ACQ_PROTOCOLS = {
    "SSBIntegrationComplex": "IQIntegration",
    "ThresholdedAcquisition": "ThresholdedIQIntegration",
    "NumericalWeightedIntegration": "IQIntegrationMixed",
    "WeightedThresholdedAcquisition": "ThresholdedIQIntegrationMixed",
}


def acq_protocol_name(acq_protocol: str | None) -> str | None:
    """The qblox-scheduler name of ``acq_protocol`` (old quantify-scheduler names are mapped)."""
    return LEGACY_ACQ_PROTOCOLS.get(acq_protocol, acq_protocol)


def average_repetitions(bin_mode) -> bool:
    """``average_segment_repetitions`` for an old ``bin_mode`` (``"average"`` or ``"append"``)."""
    mode = str(getattr(bin_mode, "value", bin_mode)).lower()
    if mode not in ("average", "append"):
        raise ValueError(f"bin_mode must be 'average' or 'append', not {bin_mode!r}")
    return mode == "average"
