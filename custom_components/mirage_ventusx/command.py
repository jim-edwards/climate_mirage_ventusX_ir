"""InfraredCommand subclasses for the Mirage VentusX protocol."""

from __future__ import annotations

from homeassistant.components.infrared import InfraredCommand

from .ir_encoder import (
    AEHA_CARRIER_HZ,
    VENTUSX_ADDRESS,
    VENTUSX_WAKE_PACKET,
    build_packet,
    mirage_combined_timings,
)


class MirageVentusXCommand(InfraredCommand):
    """Wake frame immediately followed by the data frame in a single transmission.

    Combining both frames eliminates the HA→ESPHome network round-trip that would
    otherwise introduce variable latency between them, ensuring the inter-packet
    gap stays close to what the physical remote produces (~33 ms).
    """

    def __init__(
        self,
        hvac_mode: str,
        temp_c: float,
        fan_mode: str,
        swing_mode: str,
    ) -> None:
        super().__init__(modulation=AEHA_CARRIER_HZ, repeat_count=0)
        self._timings = mirage_combined_timings(
            VENTUSX_ADDRESS,
            VENTUSX_WAKE_PACKET,
            build_packet(hvac_mode, temp_c, fan_mode, swing_mode),
        )

    def get_raw_timings(self) -> list[int]:
        return self._timings
