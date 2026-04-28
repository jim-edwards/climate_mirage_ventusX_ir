"""Mirage VentusX IR climate entity."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.components.climate import (
    SWING_BOTH,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_VERTICAL,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
)
from homeassistant.components.infrared import (
    InfraredEmitterConsumerEntity,
    InfraredReceivedSignal,
    async_subscribe_receiver,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.util.unit_conversion import TemperatureConverter
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .command import MirageVentusXDataCommand, MirageVentusXWakeCommand
from .const import (
    CONF_INFRARED_EMITTER_ENTITY_ID,
    CONF_INFRARED_RECEIVER_ENTITY_ID,
    DOMAIN,
    TEMP_MAX,
    TEMP_MIN,
    TEMP_STEP,
)
from .ir_encoder import VENTUSX_WAKE_PACKET, aeha_decode, build_packet, decode_packet

_LOGGER = logging.getLogger(__name__)

_HVAC_MODES = [
    HVACMode.OFF,
    HVACMode.COOL,
    HVACMode.HEAT,
    HVACMode.DRY,
    HVACMode.FAN_ONLY,
    HVACMode.HEAT_COOL,
]
_FAN_MODES = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]
_SWING_MODES = [SWING_OFF, SWING_VERTICAL, SWING_HORIZONTAL, SWING_BOTH]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([MirageVentusXClimate(entry)])


class MirageVentusXClimate(ClimateEntity, InfraredEmitterConsumerEntity, RestoreEntity):
    """Climate entity controlling a Mirage VentusX mini-split via IR."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_assumed_state = True  # IR-only; updated when receiver is present but not guaranteed
    _last_transmit_time: float = 0.0
    _attr_should_poll = False
    _attr_hvac_modes = _HVAC_MODES
    _attr_fan_modes = _FAN_MODES
    _attr_swing_modes = _SWING_MODES
    _attr_min_temp = TEMP_MIN
    _attr_max_temp = TEMP_MAX
    _attr_target_temperature_step = TEMP_STEP
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
    )

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._infrared_emitter_entity_id: str = entry.data[CONF_INFRARED_EMITTER_ENTITY_ID]
        self._infrared_receiver_entity_id: str | None = entry.data.get(
            CONF_INFRARED_RECEIVER_ENTITY_ID
        )
        self._attr_unique_id = entry.entry_id
        self._attr_hvac_mode = HVACMode.COOL
        self._attr_target_temperature = 24.0
        self._attr_fan_mode = FAN_AUTO
        self._attr_swing_mode = SWING_OFF
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Mirage",
            model="Ventus X",
        )

    async def async_added_to_hass(self) -> None:
        _LOGGER.warning(
            "MirageVentusX entity setup: emitter=%s receiver=%s",
            self._infrared_emitter_entity_id,
            self._infrared_receiver_entity_id,
        )
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            valid_modes = {m.value for m in _HVAC_MODES}
            if last.state in valid_modes:
                self._attr_hvac_mode = HVACMode(last.state)
            attrs = last.attributes
            if ATTR_TEMPERATURE in attrs:
                stored_temp = float(attrs[ATTR_TEMPERATURE])
                # state_attributes stores temperature in the HA system unit (°F on
                # a Fahrenheit system), not the entity's native unit (°C).
                ha_unit = self.hass.config.units.temperature_unit
                if ha_unit != UnitOfTemperature.CELSIUS:
                    stored_temp = TemperatureConverter.convert(
                        stored_temp, ha_unit, UnitOfTemperature.CELSIUS
                    )
                self._attr_target_temperature = stored_temp
            if "fan_mode" in attrs and attrs["fan_mode"] in _FAN_MODES:
                self._attr_fan_mode = attrs["fan_mode"]
            if "swing_mode" in attrs and attrs["swing_mode"] in _SWING_MODES:
                self._attr_swing_mode = attrs["swing_mode"]
        if self._infrared_receiver_entity_id:
            _LOGGER.debug(
                "Subscribing to IR receiver entity: %s",
                self._infrared_receiver_entity_id,
            )

            @callback
            def _try_subscribe(now: Any = None) -> None:
                try:
                    self.async_on_remove(
                        async_subscribe_receiver(
                            self.hass,
                            self._infrared_receiver_entity_id,  # type: ignore[arg-type]
                            self._handle_signal,
                        )
                    )
                    _LOGGER.debug(
                        "IR receiver subscription registered for %s",
                        self._infrared_receiver_entity_id,
                    )
                except HomeAssistantError:
                    _LOGGER.debug(
                        "IR receiver %s not yet available, retrying in 30 s",
                        self._infrared_receiver_entity_id,
                    )
                    self.async_on_remove(
                        async_call_later(self.hass, 30, _try_subscribe)
                    )

            _try_subscribe()
        else:
            _LOGGER.debug("No IR receiver configured — remote tracking disabled")

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._attr_hvac_mode = hvac_mode
        await self._async_send_ir()
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = float(temp)
        if (mode := kwargs.get("hvac_mode")) is not None:
            self._attr_hvac_mode = HVACMode(mode)
        await self._async_send_ir()
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        self._attr_fan_mode = fan_mode
        await self._async_send_ir()
        self.async_write_ha_state()

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        self._attr_swing_mode = swing_mode
        await self._async_send_ir()
        self.async_write_ha_state()

    async def _async_send_ir(self) -> None:
        self._last_transmit_time = time.monotonic()
        hvac_mode = self._attr_hvac_mode
        temp_c = self._attr_target_temperature or 24.0
        fan_mode = self._attr_fan_mode or FAN_AUTO
        swing_mode = self._attr_swing_mode or SWING_OFF

        mode_str = hvac_mode.value if isinstance(hvac_mode, HVACMode) else hvac_mode
        _LOGGER.debug(
            "Sending IR: mode=%s temp=%.1f°C fan=%s swing=%s",
            mode_str, temp_c, fan_mode, swing_mode,
        )

        data_pkt = build_packet(mode_str, temp_c, fan_mode, swing_mode)
        wake_cmd = MirageVentusXWakeCommand()
        data_cmd = MirageVentusXDataCommand(mode_str, temp_c, fan_mode, swing_mode)
        _LOGGER.debug("Wake packet  : %s", VENTUSX_WAKE_PACKET.hex())
        _LOGGER.debug("Wake timings : %s", wake_cmd.get_raw_timings())
        _LOGGER.debug("Data packet  : %s", data_pkt.hex())
        _LOGGER.debug("Data timings : %s", data_cmd.get_raw_timings())
        await self._send_command(wake_cmd)
        # Hardware transmits wake body (~117 ms) + 65.5 ms trailing gap = ~182 ms.
        # Sleep 250 ms so the hardware finishes before we queue the data packet.
        await asyncio.sleep(0.25)
        await self._send_command(data_cmd)
        _LOGGER.debug("Wake + data sent")

    @callback
    def _handle_signal(self, signal: InfraredReceivedSignal) -> None:
        """Update state from a signal picked up by the IR receiver."""
        _LOGGER.debug(
            "_handle_signal: %d timings, modulation=%s, timings=%s",
            len(signal.timings),
            signal.modulation,
            signal.timings,
        )
        elapsed = time.monotonic() - self._last_transmit_time
        if elapsed < 0.5:
            _LOGGER.debug("Echo suppressed (%.3f s since last transmit)", elapsed)
            return
        result = aeha_decode(signal.timings)
        if result is None:
            _LOGGER.debug(
                "aeha_decode returned None — first 6 timings: %s",
                signal.timings[:6],
            )
            return
        address, data = result
        _LOGGER.debug("AEHA decoded: address=0x%04X data=%s", address, data.hex())
        state = decode_packet(address, data)
        if state is None:
            _LOGGER.debug(
                "decode_packet returned None for address=0x%04X data=%s",
                address,
                data.hex(),
            )
            return
        _LOGGER.debug("IR remote state: %s", state)
        self._attr_hvac_mode = HVACMode(state["hvac_mode"])
        self._attr_target_temperature = float(state["temp_c"])
        self._attr_fan_mode = str(state["fan_mode"])
        self._attr_swing_mode = str(state["swing_mode"])
        self.async_write_ha_state()
