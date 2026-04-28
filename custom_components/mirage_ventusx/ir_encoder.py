"""Pure-Python encoder for the Mirage VentusX AEHA IR protocol.

No Home Assistant imports — safe to unit-test standalone.

Packet structure: 12 bytes, AEHA-framed at 38 kHz with a 16-bit address of
0xC4D3.  A hard-coded wake packet is always sent first (180 ms inter-packet
gap) followed by the 12-byte data packet.

Output: signed-µs mark/space lists suitable for the HA infrared framework's
``InfraredCommand.get_raw_timings()`` API.  Positive values = mark (IR LED
on), negative values = space (LED off).
"""

from __future__ import annotations
from typing import Final

# ---------------------------------------------------------------------------
# AEHA protocol constants
# ---------------------------------------------------------------------------

AEHA_CARRIER_KHZ: Final = 38
_T_US: Final = 425  # 1T in microseconds (AEHA standard)

# ---------------------------------------------------------------------------
# Mirage VentusX protocol constants (mirrors mirage_ventusx.cpp)
# ---------------------------------------------------------------------------

VENTUSX_ADDRESS: Final = 0xC4D3

VENTUSX_WAKE_PACKET: Final = bytes([
    0x64, 0x40, 0x00, 0x02,
    0x04, 0x00, 0x03, 0x00,
    0x00, 0x00, 0x00, 0xA2,
])

_B3_POWER:     Final = 0x20
_B3_ALWAYS:    Final = 0x04
_B4_MODE_AUTO: Final = 0x10
_B4_MODE_HEAT: Final = 0x80
_B4_MODE_COOL: Final = 0xC0
_B4_MODE_DRY:  Final = 0x40
_B4_MODE_FAN:  Final = 0xE0
_B6_FAN_AUTO:  Final = 0x00
_B6_FAN_LOW:   Final = 0x40
_B6_FAN_MID:   Final = 0xC0
_B6_FAN_HIGH:  Final = 0xA0
_B6_SWING_V:   Final = 0x1C
_B10_SWING_H:  Final = 0x10
_B10_TEMP_ODD: Final = 0x20
_B10_ALWAYS:   Final = 0x01

# Temperature lookup tables indexed by (temp_f - 61) for 61–88 °F.
# Mirrors the VENTUSX_TEMP_BYTE5 / VENTUSX_TEMP_ODD arrays in the C++ source.
_TEMP_BYTE5: Final = (
    0xF0, 0xF0, 0x70, 0xB0, 0xB0, 0x30, 0x30, 0xD0, 0xD0, 0x50,
    0x50, 0x90, 0x10, 0x10, 0xE0, 0xE0, 0x60, 0x60, 0xA0, 0xA0,
    0x20, 0xC0, 0xC0, 0x40, 0x40, 0x80, 0x80, 0x00,
)
_TEMP_ODD: Final = (
    False, True,  False, False, True,  False, True,  False, True,  False,
    True,  False, False, True,  False, True,  False, True,  False, True,
    False, False, True,  False, True,  False, True,  False,
)

_MODE_TO_B4: Final = {
    "heat_cool": _B4_MODE_AUTO,
    "heat":      _B4_MODE_HEAT,
    "cool":      _B4_MODE_COOL,
    "dry":       _B4_MODE_DRY,
    "fan_only":  _B4_MODE_FAN,
}

_FAN_MAP: Final = {
    "low":    _B6_FAN_LOW,
    "medium": _B6_FAN_MID,
    "high":   _B6_FAN_HIGH,
    "auto":   _B6_FAN_AUTO,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bit_reverse(b: int) -> int:
    b = ((b & 0xF0) >> 4) | ((b & 0x0F) << 4)
    b = ((b & 0xCC) >> 2) | ((b & 0x33) << 2)
    b = ((b & 0xAA) >> 1) | ((b & 0x55) << 1)
    return b & 0xFF


def _calc_checksum(data: bytes) -> int:
    s = sum(_bit_reverse(b) for b in data) & 0xFFFF
    return _bit_reverse((s - 0x12) & 0xFF)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_packet(
    hvac_mode: str,
    temp_c: float,
    fan_mode: str,
    swing_mode: str,
) -> bytes:
    """Build the 12-byte Mirage VentusX data packet.

    Args:
        hvac_mode:  HA HVACMode value string ("off", "cool", "heat", …)
        temp_c:     Target temperature in °C (clamped to 61–88 °F range)
        fan_mode:   HA fan mode string ("auto", "low", "medium", "high")
        swing_mode: HA swing mode string ("off", "vertical", "horizontal", "both")
    """
    state = bytearray(12)
    state[0] = 0x64  # device ID
    state[1] = 0x80  # data packet marker
    state[2] = 0x00

    powered_on = hvac_mode != "off"
    if powered_on:
        state[3] |= _B3_POWER
    state[3] |= _B3_ALWAYS

    state[4] = _MODE_TO_B4.get(hvac_mode, 0x00)

    temp_f = int(round(temp_c * 9.0 / 5.0 + 32.0))
    temp_f = max(61, min(88, temp_f))
    enc = temp_f - 61
    state[5] = _TEMP_BYTE5[enc]
    if _TEMP_ODD[enc]:
        state[10] |= _B10_TEMP_ODD

    state[6] |= _FAN_MAP.get(fan_mode, _B6_FAN_AUTO)

    if swing_mode in ("vertical", "both"):
        state[6] |= _B6_SWING_V
    if swing_mode in ("horizontal", "both"):
        state[10] |= _B10_SWING_H
    state[10] |= _B10_ALWAYS

    state[11] = _calc_checksum(bytes(state[:11]))
    return bytes(state)


def aeha_timings(address: int, data: bytes) -> list[int]:
    """Encode one AEHA frame as signed-µs mark/space pairs.

    Positive values = mark (IR LED on), negative = space (LED off).
    Includes a 65.5 ms trailing gap so the hardware knows the frame has ended.
    Compatible with the HA infrared framework's ``get_raw_timings()`` contract.
    """
    T = _T_US
    timings: list[int] = [8 * T, -(4 * T)]  # header mark, header space

    for bit in range(16):  # address: 16 bits LSB first
        timings.append(T)
        timings.append(-(3 * T) if (address >> bit) & 1 else -T)

    for byte in data:  # data bytes: each LSB first
        for bit in range(8):
            timings.append(T)
            timings.append(-(3 * T) if (byte >> bit) & 1 else -T)

    timings.append(T)       # trailing mark
    timings.append(-65_500)  # trailing gap (65.5 ms idle)
    return timings


# ---------------------------------------------------------------------------
# Decode side (used by the IR receiver to update state)
# ---------------------------------------------------------------------------

# Inverse temperature lookup: index = (byte5 >> 4) & 0xF  →  °F
_TEMP_TABLE: Final = (88, 73, 81, 66, 84, 70, 77, 63, 86, 72, 79, 64, 82, 68, 75, 61)

# Decode maps: masked byte value → HA mode/fan string
_B4_TO_MODE: Final = {
    _B4_MODE_HEAT: "heat",
    _B4_MODE_COOL: "cool",
    _B4_MODE_DRY:  "dry",
    _B4_MODE_AUTO: "heat_cool",
    _B4_MODE_FAN:  "fan_only",
}
_B6_TO_FAN: Final = {
    _B6_FAN_AUTO: "auto",
    _B6_FAN_LOW:  "low",
    _B6_FAN_MID:  "medium",
    _B6_FAN_HIGH: "high",
}

# AEHA decoder timing tolerances: ±50% around nominal T
_HDR_MARK_MIN:  Final = 8 * _T_US // 2      # 1700 µs
_HDR_MARK_MAX:  Final = 8 * _T_US * 3 // 2  # 5100 µs
_HDR_SPACE_MIN: Final = 4 * _T_US // 2      # 850 µs
_HDR_SPACE_MAX: Final = 4 * _T_US * 3 // 2  # 2550 µs
_BIT_MARK_MIN:  Final = _T_US // 2          # 212 µs
_BIT_MARK_MAX:  Final = _T_US * 3 // 2      # 637 µs
_BIT_THRESHOLD: Final = 2 * _T_US           # 850 µs; space longer than this → bit '1'


def aeha_decode(timings: list[int]) -> tuple[int, bytes] | None:
    """Decode a received AEHA frame into (address, data_bytes) or None.

    Accepts the same signed-µs format as ``aeha_timings()``; positive = mark,
    negative = space.  Any trailing mark+gap pulse is harmlessly absorbed by
    discarding the fractional byte at the end of the bit stream.
    """
    n = len(timings)
    if n < 4:
        return None

    if not (_HDR_MARK_MIN  <= timings[0]          <= _HDR_MARK_MAX):
        return None
    if not (_HDR_SPACE_MIN <= abs(timings[1]) <= _HDR_SPACE_MAX):
        return None

    bits: list[int] = []
    idx = 2
    while idx + 1 < n:
        mark  = timings[idx]
        space = timings[idx + 1]
        if not (_BIT_MARK_MIN <= mark <= _BIT_MARK_MAX):
            break
        bits.append(1 if abs(space) > _BIT_THRESHOLD else 0)
        idx += 2

    if len(bits) < 24:  # 16 addr bits + at least one full data byte
        return None

    # Physical remote sends bits MSB first per byte (high address byte first).
    address   = sum(b << (15 - i) for i, b in enumerate(bits[:16]))
    data_bits = bits[16:]
    n_bytes   = len(data_bits) // 8  # trailing fractional bit silently dropped
    data      = bytes(
        sum(data_bits[i * 8 + p] << (7 - p) for p in range(8))
        for i in range(n_bytes)
    )
    return address, data


def decode_packet(address: int, data: bytes) -> dict[str, str | float] | None:
    """Decode a Mirage VentusX packet into a climate state dict or None.

    Returns keys ``hvac_mode`` (str), ``temp_c`` (float), ``fan_mode`` (str),
    ``swing_mode`` (str).  Returns None on wrong address, bad checksum, wake
    frame, or unrecognised field value.
    """
    if address != VENTUSX_ADDRESS or len(data) < 12:
        return None
    d = data
    if d[0] != 0x64:
        return None
    if d[1] == 0x40:  # wake packet — not a state update
        return None
    if d[1] != 0x80:  # unknown packet type
        return None
    if _calc_checksum(bytes(d[:11])) != d[11]:
        return None

    if not (d[3] & _B3_POWER):
        hvac_mode: str = "off"
    else:
        mode = _B4_TO_MODE.get(d[4] & 0xF0)
        if mode is None:
            return None
        hvac_mode = mode

    temp_f: int = _TEMP_TABLE[(d[5] >> 4) & 0xF]
    if d[10] & _B10_TEMP_ODD:
        temp_f += 1
    temp_c: float = round((temp_f - 32.0) * 5.0 / 9.0, 2)

    fan_mode = _B6_TO_FAN.get(d[6] & 0xE0)
    if fan_mode is None:
        return None

    swing_vert  = bool(d[6]  & _B6_SWING_V)
    swing_horiz = bool(d[10] & _B10_SWING_H)
    swing_mode  = (
        "both"       if swing_vert and swing_horiz else
        "vertical"   if swing_vert else
        "horizontal" if swing_horiz else
        "off"
    )

    return {
        "hvac_mode":  hvac_mode,
        "temp_c":     temp_c,
        "fan_mode":   fan_mode,
        "swing_mode": swing_mode,
    }
