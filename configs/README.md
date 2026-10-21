# Lab device and hardware configuration

- `quantum_device.json`: the qblox-scheduler `QuantumDevice` (qubit1, qubit2, snail and the
  qubit1_qubit2 iSWAP edge).
- `hardware_config.json`: the cluster hardware config (modules 2 and 4 QCM-RF, 7 QRM-RF, LO
  frequencies, mixer calibration, connectivity).

Both were converted from the qqea dataset snapshot of 2026-10-21 with `qsea.device`:

```python
from qsea.device import (quantum_device_from_snapshot, hardware_config_from_snapshot,
                         save_quantum_device, save_hardware_config)
save_quantum_device(quantum_device_from_snapshot("snapshot.json"), "configs/quantum_device.json")
save_hardware_config(hardware_config_from_snapshot("snapshot.json"), "configs/hardware_config.json")
```

The snapshot itself is not kept here (it holds the instruments' network addresses). What the
conversion changes: `rxy.motzoi` becomes `rxy.beta = motzoi * duration / 8` (same DRAG pulse,
checked sample by sample), `measure.acq_channel` becomes `measure.acq_label`, and the hardware
config's `config_type` becomes the bare class name. Everything else is copied as is,
including values left at NaN (`f12` of both qubits, most of `snail`).

Load them with:

```python
from qsea.device import load_quantum_device, load_hardware_config
device = load_quantum_device("configs/quantum_device.json")
hardware_cfg = load_hardware_config("configs/hardware_config.json")
```

`tools/compare_schedules.py --device configs/quantum_device.json --reference
tests/schedules/reference/qqea-4de2850-lab.json` and `tools/compare_hardware.py` check that
qsea with these configs compiles to the same schedules and cluster instructions as qqea with
the original snapshot (both run in the tests).
