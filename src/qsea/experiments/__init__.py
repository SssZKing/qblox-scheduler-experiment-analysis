"""Running experiments: data saving for now; calibration nodes, runners and the
HardwareAgent run helpers follow in later migration phases (see MIGRATION_PLAN.md).

Names are imported lazily, as in qqea, so importing one module does not pull in the rest.
"""

_EXPORTS = {
    "save_retrieve_acquisition_dataset": "qsea.experiments.saving",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in _EXPORTS:
        import importlib

        return getattr(importlib.import_module(_EXPORTS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
