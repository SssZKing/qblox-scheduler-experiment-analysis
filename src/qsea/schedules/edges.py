"""The iSWAP edge: device parameters and compilation of the ``iSWAP`` gate.

Moved here from the SNL315 notebook so that iSWAP schedules compile from the
package alone. The gate itself (``iSWAP(qC, qT)``) lives in
``qsea.schedules.two_qubit``; this edge tells the compiler to play it as a
marker on ``snail:switch`` that gates the pump generator.

In qblox-scheduler the edge is a pydantic model (like qblox-applications'
``CompositeSquareEdge``) instead of a qcodes instrument, so its parameters are
plain attributes: ``edge.iswap.pulse_duration = 400e-9``.

Usage::

    from qsea.schedules.edges import CompositeiSWAPEdge
    qubit1_qubit2 = CompositeiSWAPEdge(parent_element_name="qubit1", child_element_name="qubit2")
    quantum_device.add_edge(qubit1_qubit2)
"""

from __future__ import annotations

from typing import Literal

from qblox_scheduler import Edge, Numbers, OperationCompilationConfig, Parameter, SchedulerSubmodule
from qblox_scheduler.operations import pulse_library

__all__ = ["composite_marker_pulse", "iSWAPChannel", "CompositeiSWAPEdge"]


def composite_marker_pulse(
    pulse_frequency: float,
    pulse_amp: float,
    pulse_duration: float,
) -> pulse_library.MarkerPulse:
    """Compile an iSWAP to the pump marker on ``snail:switch``.

    ``pulse_frequency`` and ``pulse_amp`` are not played here: the pump generator
    is set outside the schedule. They sit in the device config because the
    phase corrections in ``two_qubit`` (``_detuning_residual``,
    ``_iswap_pump_amp``) read the pump frequency and power from there.
    """
    composite_pulse = pulse_library.MarkerPulse(
        duration=pulse_duration,
        port="snail:switch",
    )

    return composite_pulse


class iSWAPChannel(SchedulerSubmodule):
    """Submodule containing parameters for performing a iSWAP operation.

    Named iSWAPChannel (not iSWAP) so that ``from qsea.schedules.two_qubit
    import *`` -- which exports the iSWAP gate Operation(qC, qT) -- cannot shadow it.
    """

    pulse_frequency: float = Parameter(
        docstring=r"""The pulse frequency in Hz.""",
        unit="Hz",
        initial_value=500e6,
        vals=Numbers(min_value=0, max_value=2000e6, allow_nan=True),
    )

    pulse_amp: float = Parameter(
        docstring=r"""Amplitude of the pulse envelope.""",
        unit="dBm",
        initial_value=0.0,
        vals=Numbers(min_value=-100, max_value=30, allow_nan=True),
    )

    pulse_duration: float = Parameter(
        docstring=r"""The pulse duration in seconds.""",
        unit="s",
        initial_value=1e-6,
        vals=Numbers(min_value=0, max_value=500e-6, allow_nan=True),
    )

    # Per-iSWAP AC-Stark phases (dissertation 4.3.2 part 3). Read by
    # qsea.schedules.two_qubit._ac_stark_phases and carried in
    # the virtual-Z register of _iswap_rz_corrections. The difference
    # q1 - q2 also absorbs the pump phase phi_p, so it is only valid for
    # the pump frequency/phase it was calibrated at.
    ac_stark_phase_q1: float = Parameter(
        docstring=r"""AC-Stark phase correction of qubit1 (the parent element) per iSWAP, in degrees.""",
        unit="deg",
        initial_value=0.0,
        vals=Numbers(min_value=-720, max_value=720, allow_nan=True),
    )

    ac_stark_phase_q2: float = Parameter(
        docstring=r"""AC-Stark phase correction of qubit2 (the child element) per iSWAP, in degrees.""",
        unit="deg",
        initial_value=0.0,
        vals=Numbers(min_value=-720, max_value=720, allow_nan=True),
    )


class CompositeiSWAPEdge(Edge):
    """
    iSWAP edge between two BasicTransmonElements.

    The iSWAP is a square pump pulse from an external R&S generator, gated by the
    marker that :func:`composite_marker_pulse` puts on ``snail:switch``. The gate
    parameters live in the ``iswap`` submodule (:class:`iSWAPChannel`).
    """

    edge_type: Literal["CompositeiSWAPEdge"] = "CompositeiSWAPEdge"  # type: ignore[reportIncompatibleVariableOverride]

    iswap: iSWAPChannel

    def generate_edge_config(self) -> dict[str, dict[str, OperationCompilationConfig]]:
        """
        Generate valid device config.

        Fills in the edges information to produce a valid device config for
        qblox-scheduler making use of the
        :func:`~.circuit_to_device.compile_circuit_to_device_with_config_validation` function.
        """
        edge_op_config = {
            f"{self.name}": {
                "iSWAP": OperationCompilationConfig(
                    factory_func=composite_marker_pulse,
                    factory_kwargs={
                        "pulse_frequency": self.iswap.pulse_frequency,
                        "pulse_amp": self.iswap.pulse_amp,
                        "pulse_duration": self.iswap.pulse_duration,
                    },
                ),
            }
        }

        return edge_op_config
