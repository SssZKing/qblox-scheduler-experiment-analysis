"""The iSWAP gate and the Clifford-to-operation mapping shared by all two-qubit builders."""

from __future__ import annotations

import numpy as np
from qblox_scheduler.schedules.schedule import TimeableSchedule
from qblox_scheduler.operations import X90, Y90, IdlePulse, Operation, Rxy, X, Y

from qsea.schedules.clifford.clifford_group import (
    SingleQubitClifford,
    TwoQubitClifford,
)

# iSWAP_DELAY = 38e-9
iSWAP_DELAY = 120e-9


# Extra idle after every iSWAP (and sqrt-iSWAP) before the next operation, on top of the
# iSWAP_DELAY that waits for the RF to switch off. Measured 2026-10-02: a pump pulse changes
# the sum Stark phase of the NEXT iSWAP with a ~20 ns time constant -- back-to-back iSWAPs
# (26 ns RF gap) carry ~28 deg less sum phase per pair than iSWAPs >= ~100 ns apart, and a
# train of them shows a ~25 deg one-time phase. 0 keeps the original timing; ~100e-9 makes
# every iSWAP see the same (isolated) context. Read at call time, so it can be changed live:
# set qsea.schedules.gates.ISWAP_SETTLE (setting the name re-exported by two_qubit has no effect).
ISWAP_SETTLE = 0.0


# Extra idle inserted only between CONSECUTIVE iSWAPs (no single-qubit layer between them) in
# pyGSTi circuits, so that every iSWAP in GST sees the isolated context the Stark phases are
# calibrated in. 1Q gate -> iSWAP and iSWAP -> 1Q gate need no extra time (checked 2026-10-02
# with a software iSWAP_DELAY scan: >= 15 ns margin before, >= 40 ns after). Measured memory of
# a pump pulse on the next iSWAP: 24 deg/pair with tau ~10 ns plus 10 deg/pair with tau ~80 ns;
# 100 ns leaves ~2.9 deg/pair (~1.4 deg/gate).
# Read at call time; change it live through qsea.schedules.gates.ISWAP_CONSECUTIVE_GAP.
ISWAP_CONSECUTIVE_GAP = 100e-9


class iSWAP(Operation):
    r"""
    iSWAP gate, a common entangling gate.

    This operation can be represented by the following unitary:

    .. math::

        \mathrm{iSWAP}  = \begin{bmatrix}
            1 & 0 & 0 & 0 \\
            0 & 0 & i & 0 \\
            0 & i & 0 & 0 \\
            0 & 0 & 0 & 1 \\ \end{bmatrix}

    Parameters
    ----------
    qC
        The control device element.
    qT
        The target device element
    device_overrides
        Device level parameters that override device configuration values
        when compiling from circuit to device level.

    """

    def __init__(self, qC: str, qT: str, **device_overrides) -> None:
        device_element_control, device_element_target = qC, qT
        plot_func = "qblox_scheduler.schedules._visualization.circuit_diagram.cz"
        super().__init__(f"iSWAP ({device_element_control}, {device_element_target})")
        self.data.update(
            {
                "name": f"iSWAP ({device_element_control}, {device_element_target})",
                "gate_info": {
                    "unitary": np.array([[1, 0, 0, 0], [0, 0, 1j, 0], [0, 1j, 0, 0], [0, 0, 0, 1]]),
                    "tex": r"iSWAP",
                    "plot_func": plot_func,
                    "device_elements": [device_element_control, device_element_target],
                    "symmetric": True,
                    "operation_type": "iSWAP",
                    "device_overrides": device_overrides,
                },
            }
        )

    def __str__(self) -> str:
        gate_info = self.data["gate_info"]
        device_element_control = gate_info["device_elements"][0]
        device_element_target = gate_info["device_elements"][1]

        return (
            f"{self.__class__.__name__}(qC='{device_element_control}',qT='{device_element_target}')"
        )


def add_layers(
    sched: TimeableSchedule,
    layers: list[tuple[tuple[str, ...], list[tuple[Operation, float | None]]]],
    *,
    ref_op=None,
    ref_pt: str | None = None,
    rel_time: float = 0.0,
):
    """Add gate layers straight into ``sched``, with the timing qqea's gate subschedules had.

    ``layers`` is a list of ``(qubits, ops)``: ``qubits`` is ``("q0",)``, ``("q1",)`` or the
    pair, and ``ops`` a list of ``(operation, rel_time)`` played one after the other
    (``rel_time`` from the end of the previous one, ``None`` for 0). A ``q0`` layer follows
    the previous ``q0`` (or pair) layer, a ``q1`` layer starts with the ``q0`` layer before
    it, and a pair layer waits for both.

    Each layer used to be a sub-schedule, which qblox-scheduler normalises so that nothing
    in it starts before its start. The iSWAP pump marker deliberately starts
    ``iSWAP_DELAY - 26 ns`` before its slot, overlapping the previous gate, so its RF arrives
    26 ns after that gate; inside a sub-schedule that lead is lost and every iSWAP slips by
    94 ns. Adding the operations to ``sched`` itself keeps the lead. Zero-length
    ``IdlePulse`` markers stand in for the sub-schedules' start and end points.

    Returns the schedulable marking the end of the block (the next operation added
    without a ``ref_op`` follows it), or ``None`` if ``layers`` is empty.
    """
    if not layers:
        return None
    anchor = sched.add(IdlePulse(0.0), ref_op=ref_op, ref_pt=ref_pt, rel_time=rel_time)
    # (start, end) schedulables of the last layer on the q0 and q1 chains
    chains = [(anchor, anchor), (anchor, anchor)]
    ends = [anchor]
    for qubits, ops in layers:
        if qubits == ("q0",):
            start = sched.add(IdlePulse(0.0), ref_op=chains[0][1])
        elif qubits == ("q1",):
            # FIXME: this relies on the fact that single qubit Clifford are ALWAYS defined for
            # both, and ALWAYS in the order q0, q1
            start = sched.add(IdlePulse(0.0), ref_op=chains[0][0], ref_pt="start")
        elif qubits in (("q0", "q1"), ("q1", "q0")):
            start = sched.add(IdlePulse(0.0), ref_op=chains[0][1])
            start.add_timing_constraint(0, chains[1][1])
        else:
            raise ValueError(f"Unsupported layer qubits {qubits}")
        last = start
        for op, op_rel_time in ops:
            last = sched.add(op, ref_op=last, rel_time=op_rel_time or 0.0)
        # a sub-schedule ended at its latest end, and never before its start
        end = sched.add(IdlePulse(0.0), ref_op=last)
        end.add_timing_constraint(0, start)
        ends.append(end)
        if qubits == ("q0",):
            chains[0] = (start, end)
        elif qubits == ("q1",):
            chains[1] = (start, end)
        else:
            chains = [(start, end), (start, end)]
    block_end = sched.add(IdlePulse(0.0), ref_op=ends[0])
    for end in ends[1:]:
        block_end.add_timing_constraint(0, end)
    return block_end


def _clifford_layers(
    qubit_names: list[str],
    operation_buffer_time: float,
    clifford_gate_idx: int,
) -> list[tuple[tuple[str, ...], list[tuple[Operation, float | None]]]]:
    """The gate layers of a Clifford, as ``(qubits, [(operation, rel_time), ...])``."""
    if len(qubit_names) == 1:
        clifford_class = SingleQubitClifford
    elif len(qubit_names) == 2:  # noqa: PLR2004
        clifford_class = TwoQubitClifford
    else:
        raise NotImplementedError
    # ---- PycQED mappings ----#
    # map the pycqed qubit names to the ones used in quantify
    pycqed_qubit_map = {f"q{idx}": name for idx, name in enumerate(qubit_names)}
    # pycqed returns RB sequences as a list of strings. Map those to quantify operations
    pycqed_operation_map = {
        "I": lambda q: None,  # noqa: ARG005
        # "I": lambda q: IdlePulse(duration=100e-9),
        "X180": lambda q: X(pycqed_qubit_map[q[0]]),
        "X90": lambda q: X90(pycqed_qubit_map[q[0]]),
        "Y180": lambda q: Y(pycqed_qubit_map[q[0]]),
        "Y90": lambda q: Y90(pycqed_qubit_map[q[0]]),
        "mX90": lambda q: Rxy(qubit=pycqed_qubit_map[q[0]], phi=0.0, theta=-90.0),
        "mY90": lambda q: Rxy(qubit=pycqed_qubit_map[q[0]], phi=90.0, theta=-90.0),
        "iSWAP": lambda q: iSWAP(qC=pycqed_qubit_map[q[0]], qT=pycqed_qubit_map[q[1]]),
    }
    layers = []
    for qubits, gates in clifford_class(clifford_gate_idx).gate_decomposition():
        ops = []
        for gate in gates:
            op = pycqed_operation_map[gate](qubits)
            if op is not None:
                if gate == 'iSWAP':
                    ops.append((op, 26e-9 - iSWAP_DELAY))
                    # The AC-Stark phase (part 3) is NOT applied here as a bare
                    # constant Rz: it is carried in _iswap_rz_corrections'
                    # register so that the iSWAP's c_q0 <-> c_q1 exchange
                    # propagates it, and reaches the schedule as part of the
                    # correction pair the caller inserts after this block. See
                    # _iswap_rz_corrections for why the constant form is wrong
                    # from the second iSWAP of a block onwards.
                    ops.append((IdlePulse(duration=iSWAP_DELAY + ISWAP_SETTLE), None))
                else:
                    ops.append((op, operation_buffer_time))
        if ops:
            layers.append((qubits, ops))
    return layers


def add_clifford(
    sched: TimeableSchedule,
    qubit_names: list[str],
    operation_buffer_time: float,
    clifford_gate_idx: int,
    idle_duration: float | None = None,
    *,
    ref_op=None,
    ref_pt: str | None = None,
    rel_time: float = 0.0,
):
    """
    Add the physical operations of a Clifford gate index to ``sched``.

    Same operations and timing as :func:`index_to_operation`, but added to ``sched``
    itself rather than as a sub-schedule, which keeps the iSWAP pump lead (see
    :func:`add_layers`). Use this in schedule builders.

    Parameters
    ----------
    sched : TimeableSchedule
        Schedule to add the gate to.
    qubit_names : list[str]
        List of qubit names. Length 1 for single-qubit, 2 for two-qubit Clifford gates.
    operation_buffer_time : float
        Buffer time (in seconds) to insert between operations in the schedule.
    clifford_gate_idx : int
        Index of the Clifford gate to decompose and schedule.
    idle_duration : float | None
        If the whole Clifford is the identity, play an ``IdlePulse`` of this length
        instead of nothing, so every sequence of the same gate count has the same
        duration. ``None`` adds nothing for the identity.
    ref_op, ref_pt, rel_time
        Where the gate starts, as for ``TimeableSchedule.add``.

    Returns
    -------
    Schedulable | None
        The end of the gate (the next operation added without a ``ref_op`` follows it),
        or None if nothing was added.
    """
    layers = _clifford_layers(qubit_names, operation_buffer_time, clifford_gate_idx)
    if not layers:
        if idle_duration is None:
            return None
        # The whole Clifford is the identity, so nothing was emitted. Play a real idle of
        # one gate slot instead, so the operation still occupies time and every sequence of
        # the same gate count has the same duration.
        #
        # Note this deliberately keys off the *whole* decomposition being
        # empty, not off individual "I" entries. Those also appear as
        # structural padding around a two-qubit gate (e.g. Clifford 5760 is
        # [(q0,I),(q1,I),(q0q1,iSWAP),(q0,I),(q1,I)]), and timing them would
        # insert two spurious idle slots around every iSWAP.
        return sched.add(
            IdlePulse(duration=idle_duration), ref_op=ref_op, ref_pt=ref_pt, rel_time=rel_time
        )
    return add_layers(sched, layers, ref_op=ref_op, ref_pt=ref_pt, rel_time=rel_time)


def index_to_operation(
    qubit_names: list[str],
    operation_buffer_time: float,
    clifford_gate_idx: int,
    idle_duration: float | None = None,
) -> TimeableSchedule | None:
    """
    Convert a Clifford gate index to a TimeableSchedule of physical operations.

    Kept for code written for qqea. Added to another schedule as a sub-schedule, an iSWAP
    in it loses its pump lead (see :func:`add_layers`) and starts 94 ns late, so schedule
    builders use :func:`add_clifford` instead.

    Parameters
    ----------
    qubit_names : list[str]
        List of qubit names. Length 1 for single-qubit, 2 for two-qubit Clifford gates.
    operation_buffer_time : float
        Buffer time (in seconds) to insert between operations in the schedule.
    clifford_gate_idx : int
        Index of the Clifford gate to decompose and schedule.
    idle_duration : float | None
        See :func:`add_clifford`.

    Returns
    -------
    TimeableSchedule | None
        A TimeableSchedule containing the physical operations for the Clifford gate,
        or None if the decomposition results in no operations.

    Raises
    ------
    NotImplementedError
        If the number of qubits is not 1 or 2.

    """
    gate_sched = TimeableSchedule()
    if add_clifford(gate_sched, qubit_names, operation_buffer_time, clifford_gate_idx,
                    idle_duration) is None:
        return None
    return gate_sched
