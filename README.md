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
        agent.py        make_agent(): the HardwareAgent for configs/, plus device snapshots
        gettable.py     ScheduleGettable on the HardwareAgent, for quantify-core MeasurementControl
        calibration_nodes.py, nodes/   the calibration nodes, as in qqea
        runners.py      readout/DRAG optimisation runners (raw data); run_and_save()
        dry_run.py      dummy_agent() and simulate() for runs without hardware
        datadir.py      set_datadir(): one data directory for quantify-core and qblox-scheduler
        saving.py       save a raw acquisition dataset as a quantify experiment folder
    device.py       load/save the QuantumDevice and hardware config; convert a qqea snapshot
configs/            the lab QuantumDevice and hardware config (see configs/README.md)
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

The lab device is in `configs/`:

```python
from qsea.device import load_quantum_device, load_hardware_config
device = load_quantum_device("configs/quantum_device.json")
hardware_cfg = load_hardware_config("configs/hardware_config.json")
```

With it, qsea compiles to the same cluster instructions as qqea did with the original snapshot
(`tools/compare_hardware.py`, run by the tests).

### Running experiments

Schedules run on a qblox-scheduler `HardwareAgent`. The calibration nodes are used as in qqea,
with the agent in place of the instrument coordinator and the quantum device:

```python
from quantify_core.measurement import MeasurementControl
from qsea.experiments import CalibrationNodes, make_agent, set_datadir_from_env

set_datadir_from_env()                  # QBLOX_DATADIR, for quantify-core and qblox-scheduler
agent = make_agent()                    # configs/; cluster address from QBLOX_CLUSTER_IP
meas_ctrl = MeasurementControl("meas_ctrl")
nodes = CalibrationNodes(agent, meas_ctrl, ACQ_DELAY)   # ACQ_DELAY as in the qqea notebooks

qubit1 = agent.quantum_device.get_element("qubit1")
ok, f01 = nodes.ramsey_chevron_calibration(qubit1)
```

The cluster's address is never stored in the repo: pass `make_agent(cluster_ip=...)` or set
`QBLOX_CLUSTER_IP`. `make_agent(dummy=True)` (or `qsea.experiments.dry_run.dummy_agent()`)
uses a qblox-instruments dummy cluster instead.

Sweeps still go through quantify-core's `MeasurementControl`, now with qsea's
`ScheduleGettable` (same arguments as quantify-scheduler's, with the agent first), so datasets
keep their quantify layout (`x0`/`y0`, TUID folders) and the old analyses read them. The
dataset snapshot holds the device: `quantum_device` (the full `QuantumDevice`, hardware
config without the address, TWPA settings) and one entry per element/edge in qqea's layout.
For a one-off schedule, `run_and_save(agent, schedule, name)` runs it and saves
`<date>/<TUID>-<name>/` with the same snapshot.

Differences from qqea in the nodes: `drag_calibration` writes `rxy.beta` (it still takes
`motzoi_list`, converted to beta), and the runners take the agent
(`DRAG_calibration_sched(qubit, beta_list, agent)`). The node results, device updates and
datasets match qqea's on the lab device (`tools/compare_nodes.py`, run by the tests).
Hardware sweeps (`Schedule.loop`) are a later step.

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

Check the ported schedules, cluster instructions and calibration nodes against qqea's (also
part of the tests):

```
python tools/compare_schedules.py
python tools/compare_schedules.py --device configs/quantum_device.json --reference tests/schedules/reference/qqea-4de2850-lab.json
python tools/compare_hardware.py
python tools/compare_nodes.py
```

## License

MIT, see [LICENSE](LICENSE). `qsea/schedules/clifford/` is adapted from
[PycQED](https://github.com/DiCarloLab-Delft/PycQED_py3) and keeps its own MIT notice in
`src/qsea/schedules/clifford/LICENSE.txt`.
