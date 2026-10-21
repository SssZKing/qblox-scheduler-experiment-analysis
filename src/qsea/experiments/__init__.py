"""Running experiments: the HardwareAgent and ScheduleGettable, calibration nodes, hardware
runners, instrument drivers, data saving, and simulated data for dry runs.

Names are imported lazily, so ``import qsea.experiments.hp83732b`` (which
``qsea.schedules.single_qubit`` does) does not pull in the calibration nodes,
which themselves import ``qsea.schedules``.
"""

_EXPORTS = {
    "make_agent": "qsea.experiments.agent",
    "ScheduleGettable": "qsea.experiments.gettable",
    "set_datadir": "qsea.experiments.datadir",
    "CalibrationNodes": "qsea.experiments.calibration_nodes",
    "HP83732B": "qsea.experiments.hp83732b",
    "set_datadir_from_env": "qsea.experiments.datadir",
    "save_retrieve_acquisition_dataset": "qsea.experiments.saving",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in _EXPORTS:
        import importlib

        return getattr(importlib.import_module(_EXPORTS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
