"""Config flow for Mirage VentusX IR Climate."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components import infrared
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector

from .const import CONF_INFRARED_EMITTER_ENTITY_ID, CONF_INFRARED_RECEIVER_ENTITY_ID, DOMAIN


class MirageVentusXConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Mirage VentusX."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            # Verify at least one infrared emitter is available
            if not infrared.async_get_emitters(self.hass):
                errors["base"] = "no_emitters"
            else:
                data: dict = {
                    CONF_INFRARED_EMITTER_ENTITY_ID: user_input[CONF_INFRARED_EMITTER_ENTITY_ID],
                }
                if recv := user_input.get(CONF_INFRARED_RECEIVER_ENTITY_ID):
                    data[CONF_INFRARED_RECEIVER_ENTITY_ID] = recv
                return self.async_create_entry(title=user_input[CONF_NAME], data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Mirage VentusX"): str,
                vol.Required(CONF_INFRARED_EMITTER_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="infrared")
                ),
                vol.Optional(CONF_INFRARED_RECEIVER_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="infrared")
                ),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
