import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import climate_ir

AUTO_LOAD = ["climate_ir"]
CODEOWNERS = ["@bitflipper11"]

ventusx_ns = cg.esphome_ns.namespace("mirage_ventusx")
VentusXClimate = ventusx_ns.class_("MirageVentusXClimate", climate_ir.ClimateIR)

CONFIG_SCHEMA = climate_ir.climate_ir_with_receiver_schema(VentusXClimate).extend({})


async def to_code(config):
    var = await climate_ir.new_climate_ir(config)
