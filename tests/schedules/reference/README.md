# Reference schedules from qqea

`qqea-4de2850.json` holds the compiled timing table (start time, duration, port, clock,
acquisition flag, operation) of every schedule builder in
[qqea](https://github.com/SssZKing/qblox-quantify-experiment-analysis) at commit `4de2850`
(68 cases, 2628 pulses/acquisitions), as built by qqea's `tools/compare_schedules.py dump`
against its mock two-qubit device. The ported `qsea.schedules` builders are checked
against it.

How it was made:

- A Linux copy of the lab `qblox_env`: Python 3.9 with the exact pins from qqea's
  `environment.yml` (`qblox_env-linux-constraints.txt`; the Windows-only packages, PyQt5
  and zhinst are left out), quantify-scheduler 0.23.1, quantify-core 0.9.1,
  qblox-instruments 0.16.0.
- qqea at `4de2850` with one change: the Clifford lookups in
  `schedules/clifford/clifford_group.py` hash `ptm.astype(np.int32)` instead of
  `ptm.astype(int)`. The stored hash tables were built with 32-bit ints, which is what
  `int` means on Windows with numpy 1.x (the lab PC). On Linux, and on Windows with numpy 2,
  `int` is 64-bit and every lookup fails, so without this change the RB, iSWAP and
  tomography cases cannot be built here. The patched hash gives the same results as the
  lab PC.

```
python tools/compare_schedules.py dump --src <qqea-4de2850 with the int32 hash>/src \
    --out qqea-4de2850.json
```
