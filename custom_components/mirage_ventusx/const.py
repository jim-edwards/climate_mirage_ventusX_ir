from __future__ import annotations
from typing import Final

DOMAIN: Final = "mirage_ventusx"
CONF_INFRARED_EMITTER_ENTITY_ID: Final = "infrared_emitter_entity_id"
CONF_INFRARED_RECEIVER_ENTITY_ID: Final = "infrared_receiver_entity_id"

# Temperature limits match the 61–88 °F native range of the unit
TEMP_MIN: Final = 16.1   # 61 °F in °C
TEMP_MAX: Final = 31.1   # 88 °F in °C
TEMP_STEP: Final = 1.0
