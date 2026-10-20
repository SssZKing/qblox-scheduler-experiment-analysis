# qblox-scheduler-experiment-analysis
QBS experiment and analysis

Successor of [qblox-quantify-experiment-analysis](https://github.com/SssZKing/qblox-quantify-experiment-analysis) (`qqea`), ported from quantify-scheduler to qblox-scheduler. See [MIGRATION_PLAN.md](MIGRATION_PLAN.md) for the package versions and the migration plan.

## Package

One package, `qsea` (short for qblox-scheduler-experiment-analysis), laid out like `qqea`. Ported so far:

```
src/qsea/
    fitting/        analysis: fitting and plotting (unchanged from qqea apart from the package name)
    tomography/     analysis: state/process tomography, GST datasets (unchanged from qqea)
    experiments/
        saving.py   save a raw acquisition dataset as a quantify experiment folder
```

Still to come (MIGRATION_PLAN.md, phases 2 to 4): `schedules/`, the device elements and the iSWAP edge, and the calibration nodes on `HardwareAgent`.

Analysis still uses `quantify-core` 0.9.1 (`quantify_core.analysis`, `quantify_core.data.handling`).

## Install

A standalone env `qbs_env` (Python 3.12, Windows lock); the lab PC `qblox_env` is not touched:

```
conda env create -f environment.yml
conda activate qbs_env
```

This installs the pinned packages and `qsea` in editable mode.

## Tests

In `qbs_env`:

```
python -m pytest tests
```

## License

MIT, see [LICENSE](LICENSE).
