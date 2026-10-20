# qblox-scheduler-experiment-analysis
QBS experiment and analysis

Successor of [qblox-quantify-experiment-analysis](https://github.com/SssZKing/qblox-quantify-experiment-analysis) (`qqea`), ported from quantify-scheduler to qblox-scheduler. See [MIGRATION_PLAN.md](MIGRATION_PLAN.md) for the package versions and the migration plan.

## Package

One package, `qsea` (short for qblox-scheduler-experiment-analysis), laid out like `qqea`. Ported so far:

```
src/qsea/
    schedules/      building experiment schedules (qblox-scheduler TimeableSchedule)
        single_qubit.py, two_qubit.py, gates.py, phase.py, rb.py, iswap.py,
        tomography.py, gst.py, twpa.py, clifford/   as in qqea
        edges.py        CompositeiSWAPEdge, now a pydantic Edge (edge.iswap.pulse_duration = ...)
        acquisition.py  old acq_protocol / bin_mode / acq_index values -> qblox-scheduler
    fitting/        analysis: fitting and plotting (unchanged from qqea apart from the package name)
    tomography/     analysis: state/process tomography, GST datasets (unchanged from qqea)
    experiments/
        saving.py   save a raw acquisition dataset as a quantify experiment folder
```

The schedule builders keep their qqea names and arguments and compile to the same schedules
(`tools/compare_schedules.py`, run by the tests). Differences from qqea:

- Elements are pydantic models: parameters are attributes (`q.measure.pulse_duration`, not
  `q.measure.pulse_duration()`). Use `BasicTransmonElement` from
  `qblox_applications.qblox_scheduler.superconducting.transmon`.
- Builders that add Clifford gates use `qsea.schedules.gates.add_clifford` (and
  `gst.add_pygsti_circuit`). `index_to_operation` still exists, but as a sub-schedule it makes
  iSWAPs start 94 ns late in qblox-scheduler; see `gates.add_layers`.
- `set_twpa_pump(qubit, False)` works as before; the setting is kept in `qsea.schedules.twpa`
  (`twpa_pump_settings()`), not on the element.

Still to come (MIGRATION_PLAN.md, phases 3 and 4): the lab device and hardware configs, and the
calibration nodes and runners on `HardwareAgent`.

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

Check the ported schedules against qqea's (also part of the tests):

```
python tools/compare_schedules.py
```

## License

MIT, see [LICENSE](LICENSE). `qsea/schedules/clifford/` is adapted from
[PycQED](https://github.com/DiCarloLab-Delft/PycQED_py3) and keeps its own MIT notice in
`src/qsea/schedules/clifford/LICENSE.txt`.
