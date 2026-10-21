# Migration plan: qqea (quantify-scheduler) to qblox-scheduler

Source: [qblox-quantify-experiment-analysis](https://github.com/SssZKing/qblox-quantify-experiment-analysis) (`qqea`, 17.5k lines).
Target: this repo, running in a new standalone env `qbs_env`. The lab PC `qblox_env` stays as it is.

Status: phases 1 to 3 done: `qsea` has `fitting/`, `tomography/`, `schedules/` and the lab device in `configs/`. With the lab device, all 60 buildable cases compile to the same cluster instructions as qqea (47 compared in full; 13 rejected identically on both sides); the 5 cluster runners move in phase 4. Tests pass on the `qbs_env` pins. Everything marked *verified* below was run on 2026-10-20 (Linux, Python 3.12, and Python 3.9 for the `qblox_env` read check).

## 1. Decisions

| Question | Decision | Why |
| --- | --- | --- |
| One env or two? | Two: `qblox_env` (old, frozen) and `qbs_env` (new) | The stacks can't share an env: `qblox_env` is Python 3.9 / numpy 1.26 / qblox-instruments 0.16, while qblox-scheduler needs Python ≥ 3.10 and qblox-instruments ≥ 1.0. |
| Analysis library in `qbs_env` | Keep `quantify-core` 0.9.1 | *Verified* to work with qblox-scheduler 1.0.1 once qcodes and xarray are capped (section 2). The old fitting and tomography tests pass unchanged. |
| Unified `quantify` (26.x)? | Not needed, not used | Its `quantify[qblox-scheduler]` extra pins `qblox-scheduler>=1.0.0b6,<1.0.0b7`, and 1.0.0b6 is not available on PyPI, so the extra can't be installed. Without the extra it does import next to qblox-scheduler 1.0.1, but it brings its own copy of the scheduler API plus the Orange QS "juice" stack (bokeh, panel, influxdb), and it needs Python ≥ 3.11 and qcodes 0.56.x. It adds nothing we need. |
| Long term | **Deferred**: decide during the actual migration | Candidates are `qblox_applications.qblox_scheduler.analysis` (reads `HardwareAgent` data directly but expects fixed names: `acq_label="S_21"`, coords `amplitude`/`tau`/`frequency`; early stage, git-only, no tests or docs) and unified `quantify` (near drop-in for `quantify_core.analysis`, mature, but needs `x0`/`y0` data and adds ~45 packages incl. Orange QS's own framework (`orangeqs-juice-core`) and a qcodes 0.56.x pin). Either one removes the reliance on an archived package; qblox-applications also removes the qcodes/xarray caps. |

## 2. Package versions

`qbs_env` pins come from `requirements/qbs_env.in`. The full Windows lock (`requirements/qbs_env-win-py312.txt`) is what `environment.yml` installs.

| Package | `qblox_env` (current, lab PC) | `qbs_env` (new) | Notes |
| --- | --- | --- | --- |
| Python | 3.9.18 | **3.12** | qblox-scheduler ≥ 3.10, xarray 2026.x ≥ 3.11, qutip 5.3 ≥ 3.11 |
| quantify-scheduler | 0.23.1 | — | replaced by qblox-scheduler. End of life since 2026-07-01 (bugfixes ended 2026-06-30) |
| **qblox-scheduler** | — | **1.0.1** (+ `[cli]`) | released 2026-10-12; `[cli]` adds the migration tool |
| **qblox-applications** | — | **git @ `771b6c4`** (2026-10-02) | Not on PyPI. Install from GitLab, which needs `git`. Provides `BasicTransmonElement`, `CompositeSquareEdge` and the analysis classes |
| qblox-instruments | 0.16.0 | **1.4.1** | cluster firmware: see section 3 |
| quantify-core | 0.9.1 | 0.9.1 | **end of life**: its README says it is archived and everything moved to unified `quantify`. Last release 2025-08, no commits since 2025-11. Kept for now; long-term replacement deferred (section 1) |
| qcodes | 0.46.0 | **0.56.0 (cap)** | 0.57 removed `qcodes.utils.helpers`, which quantify-core imports (*verified*: 0.52–0.56 OK, 0.57+ fail). qblox-instruments 1.4.1 needs ≥ 0.52 |
| xarray | 2024.2.0 | **2026.2.0 (cap)** | 2026.4+ raises `TypeError` in `write_dataset`, in quantify-core **and in qblox-scheduler 1.0.1's own `AdapterH5NetCDF`** (*verified*), so the cap is needed even without quantify-core |
| numpy | 1.26.4 | 2.5.4 | numpy 2: check our own code for removed aliases (`np.float_`, `np.complex_`, …) |
| scipy | 1.12.0 | 1.18.1 | |
| pandas | 2.2.1 | 3.0.6 | |
| matplotlib | 3.8.3 | 3.11.2 | |
| lmfit | 1.2.2 | 1.3.4 | uncertainties 3.2.2 (quantify-core needs < 3.2.3) |
| pydantic | 2.6.3 | 2.13.5 | qblox-scheduler needs 2.12–2.13.5 |
| qutip | 5.0.2 | 5.3.1 | |
| pygsti | 0.9.14.3 | 0.10.2 | |
| scikit-rf | 0.32.0 | 2.2.0 | |
| h5netcdf / h5py / netcdf4 | 1.3.0 / 3.10.0 / 1.7.2 | 1.8.1 / 3.16.0 / 1.7.1.post2 | |
| PyQt5 / pyqt5-qt5 | 5.15.10 / 5.15.2 | 5.15.11 / 5.15.2 | quantify-core needs PyQt5; qblox-scheduler caps pyqt5-qt5 ≤ 5.15.2 on Windows |
| jupyterlab | 4.4.1 | 4.6.4 | |

Not carried over from `qblox_env` (unused by qqea): zhinst*, scqubits, spirack (still pulled in by qblox-instruments), broadbean (still pulled in by qcodes), stim (still pulled in by pygsti).

### What was verified in this env

- `uv pip compile` resolves for Windows and Linux on Python 3.12 (the two locks differ only in the Linux-only `pexpect`/`ptyprocess`, Windows-only `pywinpty`, and `pyqt5-qt5`).
- Old repo `tests/test_fitting.py`, `tests/test_iswap_exchange.py`, `tests/tomography/`: **58 passed, 1 skipped** against numpy 2.5.4, pandas 3.0.6, pygsti 0.10.2, qutip 5.3.1, lmfit 1.3.4.
- `quantify_core` `RabiAnalysis`, `CosineAnalysis`, `T1Analysis` run end to end, and `write_dataset`/`load_dataset` work.
- `HardwareAgent(..., create_dummy_connections=True).run(schedule)` with a `Schedule.loop` sweep works on a dummy cluster. It saves `datadir/YYYYMMDD/<TUID>/dataset.hdf5` + `snapshot.json`, the same layout as quantify-core. `quantify_core.data.handling.load_dataset(tuid)` reads it.
- A complex-valued dataset written by qblox-scheduler in `qbs_env` loads with `quantify_core.load_dataset` in **Python 3.9 with `qblox_env`'s pins**, and the values match. Old notebooks in `qblox_env` can analyse new data.

## 3. Hardware constraint: cluster firmware

| | qblox-instruments | Cluster firmware |
| --- | --- | --- |
| `qblox_env` | 0.16.0 | **0.11.0 exactly** |
| `qbs_env` | 1.4.1 (qblox-scheduler 1.x) | **≥ 0.17.0, < 2.0.0** |

One cluster can't run both. After the firmware upgrade, `qblox_env` can no longer drive the hardware. It stays useful for old notebooks, dry runs and analysis of any data (old or new, see above). Consequences:

1. Before the upgrade, record reference data in `qblox_env`: resonator spectroscopy, Rabi, T1/T2/Ramsey, readout fidelity, single-qubit RB, iSWAP chevron and RB. Also save the full device snapshot. These are the baselines for checking `qbs_env` on hardware.
2. The upgrade is the cutover point: do it only after phases 1–5 pass dry runs.
3. Optional fallback if a hardware-capable old stack is needed after the upgrade: a third "bridge" env with quantify-scheduler 0.28.1 + qblox-instruments 1.4.1 + quantify-core 0.9.1 on Python 3.10/3.11. It resolves (*verified*, qcodes 0.52.0) but is untested on hardware, and it is a second migration of qqea (0.23 to 0.28), so only build it if needed.

## 4. What changes in the code (quantify-scheduler 0.23 to qblox-scheduler 1.0)

The official tool, `qblox-scheduler migrate-scripts <path>`, was run on a scratch copy of `qqea/src`. It rewrote 16 of 50 files (+128/−160 lines): imports, renamed kwargs, acquisition classes, DRAG beta. Afterwards 8 modules still failed to import. What's left is manual:

| Change | Where in qqea | Size | Handling |
| --- | --- | --- | --- |
| `ScheduleGettable` and `MeasurementControl` removed. Sweeps become `Schedule.loop(linspace(...))` run by `HardwareAgent.run(schedule)`, which returns and saves the dataset | `experiments/nodes/_base.py`, `nodes/*`, `calibration_nodes.py`, `runners.py`, `dry_run.py`, `saving.py`, `simulated_data.py`, `schedules/iswap.py` (10 files, ~50 sites) | **largest** | Rewrite the node base class around `HardwareAgent`. `InstrumentCoordinator`/`ClusterComponent`/`Cluster` setup moves into the agent (hardware config + device config). Dry runs use `create_dummy_connections=True`. `saving.py` mostly goes away (the agent saves) |
| Device elements are pydantic models, not qcodes instruments: `q.clock_freqs.f01(5e9)` becomes `q.clock_freqs.f01 = 5e9` | ~70 calls in `schedules/single_qubit.py`, `nodes/readout.py`, `nodes/single_qubit.py`, `runners.py`, `gst.py`, `tomography.py`, `fitting/readout.py` | medium | The tool only rewrites module-level instances. Calls on function arguments (most of ours) are manual |
| `BasicTransmonElement` moved to `qblox_applications.qblox_scheduler.superconducting.transmon` and must be imported before a device config is loaded (that import registers the element type) | 5 files | small | one import module in the new package |
| Custom per-qubit TWPA flag via `element.add_parameter(...)` (impossible on pydantic models) | `schedules/twpa.py` | small | **done**: `set_twpa_pump`/`twpa_pump_enabled` keep their API and store the flag by element name in `qsea.schedules.twpa` (`twpa_pump_settings()` for snapshots); the device config stays standard. Alternative if wanted: a `BasicTransmonElement` subclass with a `twpa_pump` field |
| `CompositeiSWAPEdge` (qcodes `InstrumentChannel` + `ManualParameter`s) | `schedules/edges.py` | small–medium | Rewrite as a pydantic `Edge` with an `iSWAP(SchedulerSubmodule)` block, copying `CompositeSquareEdge`/`CZ` in qblox-applications |
| Old `Schedule` is now `qblox_scheduler.schedules.schedule.TimeableSchedule`. The new top-level `qblox_scheduler.Schedule` supports loops. The tool's `...schedule import Schedule` rewrite fails to import | ~9 imports | small | use `qblox_scheduler.Schedule` for new loop-based builders and `TimeableSchedule` where explicit timing is needed |
| `bin_mode` removed (dropped silently by the tool). Single-shot data uses `average_segment_repetitions=False` | 35 sites | medium | check every single-shot readout path (g/e discrimination, readout optimisation, tomography, GST) |
| **DRAG: `D_amp` became `beta`, and the derivative scales as `beta/sigma²` instead of `D_amp/sigma`**, so `beta = D_amp·sigma` | 29 sites + **stored calibration values** | small code, **high risk** | The tool rewrites call sites but not saved `rxy.beta`/DRAG values in device JSON or notebooks. Recalibrate DRAG or convert saved values explicitly |
| `amp` → `amplitude`, `G_amp` → `amplitude`, `acq_channel` → `acq_label`, `SSBIntegrationComplex` → `IQIntegration`, `ThresholdedAcquisition` → `ThresholdedIQIntegration`, `t0` removed (use `rel_time`) | throughout `schedules/` | done by tool | review the diff |
| `qcodes.instrument.parameter` → `qcodes.parameters`, `qcodes.instrument.base` deprecated | `edges.py`, `hp83732b.py` | small | HP83732B driver otherwise fine with qcodes 0.56 |
| Device/hardware JSON configs | lab configs | small | `qblox-scheduler migrate-configs <dir>` |
| New dataset layout: dims `acq_index_<n>`, variables named by `acq_label` (`"0"`, …), sweep values as named coords, instead of quantify's `x0…/y0…` | every `quantify_core.analysis` call and every fit that reads `ds.x0`/`ds.y0` | medium | Phase 5 adapter (below) |
| **Found in phase 2:** every sub-schedule's timing is normalised so nothing in it starts before its start (qblox-scheduler `compilation.py`; quantify-scheduler did this only for the top level). The iSWAP pump marker starts `iSWAP_DELAY − 26 ns` before its slot, inside the gate sub-schedule, so every iSWAP slipped by 94 ns (and the tomography/GST phase corrections moved by ~6.8°) | `gates.index_to_operation`, `gst.pygsti_circuit_to_operation` and all their callers | medium | **done**: `add_clifford` / `add_pygsti_circuit` add the gate layers straight into the caller's schedule (`gates.add_layers`); `index_to_operation` stays for old code |
| **Found in phase 2:** `repetitions` became a loop whose body starts with a `ResetClockPhase` of every used clock and a 4 ns idle | every schedule | none | expected; each shot is 4 ns longer |
| **Found in phase 2:** `acq_index` removed: bins follow the acquisition order; `HardwareAgent.run` averages acquisitions with equal `coords` | ~60 sites | small | **done**: `acq_index=i` → `coords={"acq_index": i}`; old `acq_protocol`/`bin_mode` values still accepted (`qsea.schedules.acquisition`) |
| **Found in phase 2:** `SetClockFrequency(clock_freq_new=)` → `frequency=`; `Operation._update()` gone (custom `iSWAP` gate) | 9 + 1 sites | small | **done** |
| **Found in phase 2:** qqea's Clifford lookups hash `ptm.astype(int)`, which matches the stored tables only where `int` is 32-bit (Windows + numpy 1.x). With numpy 2 on the lab PC every RB/iSWAP/tomography/GST builder would fail | `schedules/clifford/clifford_group.py` | tiny | **done** in qsea (`np.int32`); the same latent bug is in qqea |

Unchanged: `fitting/` and `tomography/` have no quantify-scheduler imports and pass their tests in `qbs_env`. `schedules/clifford/` (PycQED) is pure Python.

## 5. Phases

Each phase ends with tests green in `qbs_env`. Phases 1–5 need no hardware.

0. **Environment.** `conda env create -f environment.yml` on the lab PC. Run `pip check`, then an import smoke test of `qblox_scheduler`, `qblox_applications`, `quantify_core.analysis`, `pygsti`, `qutip`. Commit the frozen `conda env export` next to the lock.
1. **Scaffold and analysis port.** Package `qsea` (qblox-scheduler-experiment-analysis) in this repo, same layout as `qqea`. Copy `fitting/` and `tomography/` with their tests unchanged. Add CI-style `pytest` (fast tests only).
2. **Schedules (done).** `schedules/` ported 1:1 to `TimeableSchedule`. Checked against reference timing tables from qqea (`tests/schedules/reference/`, built in a Linux copy of `qblox_env`) with `tools/compare_schedules.py`, which also runs as `tests/schedules/test_reference_schedules.py`: 63 cases identical, 5 runner cases pending phase 4. Every DRAG pulse in the builders has `D_amp=0`, so the beta scaling does not change them; the DRAG calibration runner (phase 4) is where it matters. Turning sweeps into `Schedule.loop` is left to phase 4, when the nodes move to `HardwareAgent` and loops pay off; the 1:1 port keeps the builders comparable with qqea.
3. **Device and configs (done).** `qsea.device` converts a qqea dataset snapshot: elements to qblox-applications `BasicTransmonElement` (`rxy.motzoi` → `rxy.beta = motzoi·duration/8`, identical DRAG samples; `acq_channel` → `acq_label`), the iSWAP edge to `CompositeiSWAPEdge`, and the hardware config (`config_type` only; same as `qblox-scheduler migrate-configs`). `configs/` holds the lab device and hardware config converted from the 2026-10-21 snapshot (the raw snapshot is not committed: it has the instruments' IP addresses). Checked twice against qqea built with that snapshot: timing tables (`tools/compare_schedules.py --device ...`) and cluster instructions per module/sequencer: LO/NCO frequencies, attenuation, calibration, integration/threshold settings, waveform and weight samples (`tools/compare_hardware.py`). Differences found: qblox-scheduler leaves the mixer phase/gain corrections unset instead of writing 0/1 (auto sideband calibration is on, so no effect), and it refuses an NCO frequency beyond ±500 MHz at compile time where quantify-scheduler only failed on upload. `f12` is NaN on both qubits, so f-state builders cannot compile with this device (same in qqea).
4. **Execution layer.** Rewrite `experiments/nodes/_base.py` around `HardwareAgent(hw_config, device).run(schedule)`. Port the calibration nodes topic by topic (single_qubit, readout, iswap_stark, roadmap) and the `runners.py` DRAG/readout optimisation. Save every run through a `qsea` helper (`run_and_save`) instead of the agent's default save. By default `HardwareAgent.run` writes `<date>/<TUID>/` with no experiment name. Its `snapshot.json` holds only timestamp, platform and Python version: no device or instrument settings. And in 1.0.1, `ExperimentDataContainer.get_latest_tuid`/`get_tuids_containing` always raise (a `Path` vs `str` comparison). The helper runs with `save_to_experiment=False`, then writes `<date>/<TUID>-<name>/dataset.hdf5`. Its `snapshot.json` holds the `QuantumDevice` JSON, the hardware config and the qcodes snapshots of the clusters and external instruments (prototype *verified* on a dummy cluster; `quantify_core` `get_latest_tuid(contains=...)`, `load_dataset` and `load_snapshot` all work on it). Point `QBLOX_DATADIR` at both `OutputDirectoryManager.set_datadir` and `quantify_core.data.handling.set_datadir` so old analyses find new TUIDs. Dry-run every node with `create_dummy_connections=True` (rewrite `dry_run.py` and its tests).
5. **Analysis bridge.** A small adapter: qblox-scheduler dataset (acq_index dims, acq_label vars, named coords) to quantify dataset v2 (`x0…`, `y0…` with `units`/`long_name`, `tuid`). Existing quantify-core analyses and `fitting/` keep working through it. Test it against `simulated_data.py`. The adapter stays in place until the long-term analysis library is chosen (section 1, deferred).
6. **Hardware cutover.** Record baselines in `qblox_env` (section 3), upgrade the cluster firmware to ≥ 0.17 (match qblox-instruments 1.4.1), then repeat the baselines in `qbs_env` and compare. Keep `qblox_env` for legacy notebooks and analysis.

## 6. Open questions

Decided:
- Package name `qsea`.
- Keep `quantify-core` 0.9.1 for analysis for now (long-term library deferred).
- Sweeps: hardware loops (`Schedule.loop`) wherever the swept quantity is a schedule parameter; `SetParameter`/`Callback` software loops only for external instruments (HP83732B, LOs).

Pending input:
- (received 2026-10-21) Lab snapshot and hardware config: converted into `configs/`.

Still open:

- **How sweeps run (verified on a dummy cluster, for reference)**: inside `Schedule.loop`, a body of only pulses and acquisitions compiles to one real-time loop on the cluster. A body containing `SetParameter(qcodes_param, var)` or `Callback(fn, var)` runs as a Python loop: one parameter set and one compiled sub-schedule per point, with any inner pulse-only loop still real-time. The result is one flat dataset (`acq_index_0`) with the swept values as coords; reshape it with `qblox_applications...analysis.helpers.acq_coords_to_dims`. `Callback` needs a module-level function (it is stored by import path; lambdas and closures fail).
- **qblox-applications**: not on PyPI, no tags yet. It is pinned to a commit; switch to a PyPI release once one exists.
- **Firmware upgrade timing**: who does it, and when the reference data from `qblox_env` gets taken.
- **Python 3.12 on the lab PC**: confirm conda can install it there (any Python ≥ 3.11 works with these pins).
