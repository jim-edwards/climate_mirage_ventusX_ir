"""InfraredCommand subclasses for the Mirage VentusX protocol."""

from __future__ import annotations

from homeassistant.components.infrared import InfraredCommand

from .ir_encoder import (
    AEHA_CARRIER_KHZ,
    VENTUSX_ADDRESS,
    VENTUSX_WAKE_PACKET,
    aeha_timings,
    build_packet,
)


class MirageVentusXWakeCommand(InfraredCommand):
    """Wake frame only — sent first, before the data frame."""

    _timings: list[int] = aeha_timings(VENTUSX_ADDRESS, VENTUSX_WAKE_PACKET)

    def __init__(self) -> None:
        super().__init__(modulation=AEHA_CARRIER_KHZ, repeat_count=0)

    def get_raw_timings(self) -> list[int]:
        return self._timings


class MirageVentusXDataCommand(InfraredCommand):
    """Data frame — sent after a ~250 ms delay following the wake frame."""

    def __init__(
        self,
        hvac_mode: str,
        temp_c: float,
        fan_mode: str,
        swing_mode: str,
    ) -> None:
        super().__init__(modulation=AEHA_CARRIER_KHZ, repeat_count=0)
        self._timings = aeha_timings(
            VENTUSX_ADDRESS,
            build_packet(hvac_mode, temp_c, fan_mode, swing_mode),
        )

    def get_raw_timings(self) -> list[int]:
        return self._timings
