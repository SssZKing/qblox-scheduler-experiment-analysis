"""Point the data directory at ``QBLOX_DATADIR``, for quantify-core and qblox-scheduler alike."""

import os
from pathlib import Path

ENV_VAR = "QBLOX_DATADIR"


def set_datadir(datadir) -> Path:
    """Use ``datadir`` for both quantify-core (``MeasurementControl``, ``load_dataset``,
    analyses) and qblox-scheduler (``HardwareAgent``, ``ExperimentDataContainer``)."""
    from qblox_scheduler import OutputDirectoryManager
    from quantify_core.data.handling import set_datadir as qc_set_datadir

    datadir = Path(datadir).expanduser()
    qc_set_datadir(str(datadir))
    OutputDirectoryManager.set_datadir(datadir)
    return datadir


def get_datadir() -> Path:
    """The data directory quantify-core uses (kept equal to qblox-scheduler's by :func:`set_datadir`)."""
    from quantify_core.data.handling import get_datadir as qc_get_datadir

    return Path(qc_get_datadir())


def set_datadir_from_env(env_var: str = ENV_VAR) -> Path:
    """Call :func:`set_datadir` with the folder named by ``env_var``.

    Returns the data directory. Raises ``RuntimeError`` if the variable is
    unset or empty, and ``FileNotFoundError`` if the folder does not exist
    (quantify would otherwise create an empty one silently).
    """
    value = os.environ.get(env_var, "").strip()
    if not value:
        raise RuntimeError(
            f"{env_var} is not set. Set it to the quantify data folder for this "
            f"session, e.g. `set {env_var}=C:\\path\\to\\data` in cmd before starting Jupyter."
        )
    datadir = Path(value).expanduser()
    if not datadir.is_dir():
        raise FileNotFoundError(f"{env_var}={value} is not an existing folder.")
    return set_datadir(datadir)
