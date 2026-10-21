# Reference node runs from qqea

`qqea-4de2850-lab-nodes.json` holds what each of 19 calibration nodes of
[qqea](https://github.com/SssZKing/qblox-quantify-experiment-analysis) at commit `4de2850`
did on the lab device: its `(ok, value)` result, the device parameters it wrote afterwards,
and every dataset it saved (variables, coordinates, names, units, values and attributes).
`tools/compare_nodes.py` runs the qsea nodes the same way and compares; it also runs as
`tests/experiments/test_reference_nodes.py`.

How it was made: in the Linux copy of `qblox_env` and the int32-hash qqea described in
`tests/schedules/reference/README.md`, with the device of the 2026-10-21 lab snapshot:

```
python tools/compare_nodes.py dump-qqea --qqea <qqea-4de2850 with the int32 hash> \
    --snapshot <snapshot.json> --out tests/experiments/reference/qqea-4de2850-lab-nodes.json
```

Both sides compile every schedule and upload it to a qblox-instruments dummy cluster (0.16
in qqea, 1.4.1 in qsea). Only the acquired data is replaced, by the same deterministic
simulated signals on both sides (a resonator dip, Rabi oscillations, T1/T2 decays, Ramsey
fringes, RB decays with |g>/|e> calibration points, IQ blobs, a DRAG crossing, readout
traces), so the comparison covers the gettables, data processing, sweeps, fits, device
updates and saved datasets, not the cluster. Some nodes reject their fit on this data
(`ok=False`); they must reject it the same way.

qqea's DRAG node calibrates `rxy.motzoi`, qsea's `rxy.beta`; the reference's motzoi values
are compared as `beta = motzoi * rxy.duration / 8`.

The snapshot is not kept in the repo (it has the instruments' network addresses); this file
contains none.
