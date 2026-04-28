#include "mirage_ventusx.h"
#include "esphome/core/log.h"
#include "esphome/components/remote_base/aeha_protocol.h"

namespace esphome {
namespace mirage_ventusx {

static const char *const TAG = "mirage_ventusx.climate";

const uint8_t VENTUSX_STATE_LENGTH = 12;
const uint16_t VENTUSX_ADDRESS = 0xC4D3;

const uint8_t VENTUSX_TEMP_OFFSET = 60;

const uint8_t VENTUSX_HEADER_B0 = 0x64;
const uint8_t VENTUSX_HEADER_B1_WAKE = 0x40;
const uint8_t VENTUSX_HEADER_B1_DATA = 0x80;
const uint8_t VENTUSX_HEADER_B2 = 0x00;

const uint8_t VENTUSX_B3_BIT_DISPLAY_OFF = 0x02;
const uint8_t VENTUSX_B3_BIT_UNIT_POWER = 0x20;
const uint8_t VENTUSX_B3_BIT_UNIT_ALWAYS_SET = 0x04;

const uint8_t VENTUSX_B4_MODE_MASK = 0xF0;
const uint8_t VENTUSX_B4_MODE_HEAT = 0x80;
const uint8_t VENTUSX_B4_MODE_COOL = 0xC0;
const uint8_t VENTUSX_B4_MODE_DRY = 0x40;
const uint8_t VENTUSX_B4_MODE_AUTO = 0x10;
const uint8_t VENTUSX_B4_MODE_FAN = 0xE0;

const uint8_t VENTUSX_B4_TURBO_BIT = 0x02;

const uint8_t VENTUSX_B6_FAN_MASK = 0xE0;
const uint8_t VENTUSX_B6_FAN_AUTO = 0x00;
const uint8_t VENTUSX_B6_FAN_LOW = 0x40;
const uint8_t VENTUSX_B6_FAN_MID = 0xC0;
const uint8_t VENTUSX_B6_FAN_HIGH = 0xA0;

const uint8_t VENTUSX_B6_SWING_VERT_MASK = 0x1C;

const uint8_t VENTUSX_B10_SWING_HORIZ_BIT = 0x10;
const uint8_t VENTUSX_B10_TEMP_ODD_BIT = 0x20;
const uint8_t VENTUSX_B10_SWING_ALWAYS_SET = 0x01;

// Bit-reverse an 8-bit value (e.g. 0b00000001 -> 0b10000000)
uint8_t MirageVentusXClimate::bit_reverse(uint8_t b)
{
  b = (b & 0xF0) >> 4 | (b & 0x0F) << 4; // swap nibbles
  b = (b & 0xCC) >> 2 | (b & 0x33) << 2; // swap pairs
  b = (b & 0xAA) >> 1 | (b & 0x55) << 1; // swap bits
  return b;
}

uint8_t MirageVentusXClimate::calc_checksum(const uint8_t *data, uint8_t len)
{
  uint16_t sum = 0;
  for (size_t i = 0; i < len; ++i)
  {
    sum += bit_reverse(data[i]);
  }

  uint8_t temp = (sum - 0x12) % 256;
  return bit_reverse(temp);
}

void MirageVentusXClimate::transmit_state()
{
  this->last_transmit_time_ = millis(); // setting the time of the last transmission.
  uint8_t remote_state[VENTUSX_STATE_LENGTH] = {0};

  // Header
  remote_state[0] = VENTUSX_HEADER_B0;
  remote_state[1] = VENTUSX_HEADER_B1_DATA;
  remote_state[2] = VENTUSX_HEADER_B2;

  // Mode setup
  auto powered_on = this->mode != climate::CLIMATE_MODE_OFF;
  if (powered_on)
  {
    remote_state[3] |= VENTUSX_B3_BIT_UNIT_POWER;
  }
  remote_state[3] |= VENTUSX_B3_BIT_UNIT_ALWAYS_SET;

  switch (this->mode)
  {
    case climate::CLIMATE_MODE_HEAT_COOL:
      remote_state[4] |= VENTUSX_B4_MODE_AUTO;
      break;
    case climate::CLIMATE_MODE_HEAT:
      remote_state[4] |= VENTUSX_B4_MODE_HEAT;
      break;
    case climate::CLIMATE_MODE_COOL:
      remote_state[4] |= VENTUSX_B4_MODE_COOL;
      break;
    case climate::CLIMATE_MODE_DRY:
      remote_state[4] |= VENTUSX_B4_MODE_DRY;
      break;
    case climate::CLIMATE_MODE_FAN_ONLY:
      remote_state[4] |= VENTUSX_B4_MODE_FAN;
      break;
     default:
      break;
  }

  // Temperature — inverse of the on_receive lookup table, indexed by (temp_f - 61), 28 entries for 61–88°F
  static const uint8_t VENTUSX_TEMP_BYTE5[28] = {
      0xF0, 0xF0, 0x70, 0xB0, 0xB0, 0x30, 0x30, 0xD0, 0xD0, 0x50,
      0x50, 0x90, 0x10, 0x10, 0xE0, 0xE0, 0x60, 0x60, 0xA0, 0xA0,
      0x20, 0xC0, 0xC0, 0x40, 0x40, 0x80, 0x80, 0x00};
  static const bool VENTUSX_TEMP_ODD[28] = {
      false, true,  false, false, true,  false, true,  false, true,  false,
      true,  false, false, true,  false, true,  false, true,  false, true,
      false, false, true,  false, true,  false, true,  false};

  float temp_c = clamp(this->target_temperature, VENTUSX_TEMP_MIN, VENTUSX_TEMP_MAX);
  auto temp = (uint8_t) roundf(temp_c * 9.0f / 5.0f + 32.0f);  // convert °C → °F
  if (temp < 61) temp = 61;
  if (temp > 88) temp = 88;
  uint8_t enc = temp - 61;
  remote_state[5] = VENTUSX_TEMP_BYTE5[enc];
  if (VENTUSX_TEMP_ODD[enc])
    remote_state[10] |= VENTUSX_B10_TEMP_ODD_BIT;

  // Fan speed
  switch (this->fan_mode.value())
  {
  case climate::CLIMATE_FAN_LOW:
    remote_state[6] |= VENTUSX_B6_FAN_LOW;
    break;
  case climate::CLIMATE_FAN_MEDIUM:
    remote_state[6] |= VENTUSX_B6_FAN_MID;
    break;
  case climate::CLIMATE_FAN_HIGH:
    remote_state[6] |= VENTUSX_B6_FAN_HIGH;
    break;
  case climate::CLIMATE_FAN_AUTO:
  default:
    remote_state[6] |= VENTUSX_B6_FAN_AUTO;
    break;
  }

  // Swing 
  if (this->swing_mode == climate::CLIMATE_SWING_VERTICAL || this->swing_mode == climate::CLIMATE_SWING_BOTH)
  {
    remote_state[6] |= VENTUSX_B6_SWING_VERT_MASK;
  }
  if (this->swing_mode == climate::CLIMATE_SWING_HORIZONTAL || this->swing_mode == climate::CLIMATE_SWING_BOTH)
  {
    remote_state[10] |= VENTUSX_B10_SWING_HORIZ_BIT;
  }
  remote_state[10] |= VENTUSX_B10_SWING_ALWAYS_SET;

  // Checksum
  remote_state[11] = calc_checksum(remote_state, VENTUSX_STATE_LENGTH - 1);

  ESP_LOGVV(TAG,
            "TX VentusX\n  Header: %02X %02X %02X %02X\n  Mode: %02X\n  Temp: %02X\n  Fan: %02X\n  Reserved: %02X %02X %02X\n  Horz Swing: %02X\n  Checksum: %02X",
            remote_state[0], remote_state[1], remote_state[2], remote_state[3], remote_state[4], remote_state[5],
            remote_state[6], remote_state[7], remote_state[8], remote_state[9], remote_state[10], remote_state[11]);

  ESP_LOGD(TAG, "TX temp=%d byte5=0x%02X checksum=0x%02X", temp, remote_state[5], remote_state[11]);

  // Send the wakeup packet (hard-coded)
  esphome::remote_base::AEHAData aeha_wakeup;
  aeha_wakeup.address = VENTUSX_ADDRESS;
  uint8_t wakeup_packet[12] = {
      0x64, 0x40, 0x00, 0x02,
      0x04, 0x10, 0x03, 0x00,
      0x00, 0x00, 0x00, 0xB2};

  aeha_wakeup.data.assign(wakeup_packet, wakeup_packet + VENTUSX_STATE_LENGTH);
  auto transmit = this->transmitter_->transmit();
  auto *tx_data = transmit.get_data();
  esphome::remote_base::AEHAProtocol().encode(tx_data, aeha_wakeup);
  transmit.perform();

  delay(180);

  // Send the actual data
  esphome::remote_base::AEHAData aeha;
  aeha.address = VENTUSX_ADDRESS;
  aeha.data.assign(remote_state, remote_state + VENTUSX_STATE_LENGTH);

  transmit = this->transmitter_->transmit();
  tx_data = transmit.get_data();
  esphome::remote_base::AEHAProtocol().encode(tx_data, aeha);
  //transmit.set_send_times(2);
  transmit.perform();
}

bool MirageVentusXClimate::on_receive(remote_base::RemoteReceiveData data) {
  uint32_t now = millis();
  if (now - this->last_transmit_time_ < 500)
    return false;
  this->last_receive_ = now;

  auto decoded = esphome::remote_base::AEHAProtocol().decode(data);
  if (!decoded)
   return false;
  if (decoded->address != VENTUSX_ADDRESS)
    return false;
  if (decoded->data.size() < VENTUSX_STATE_LENGTH)
    return false;

  const uint8_t *d = decoded->data.data();

  ESP_LOGD(TAG, "RX AEHA addr=0x%04X data_size=%d", decoded->address, (int) decoded->data.size());
  ESP_LOGVV(TAG,
           "RX VentusX\n  Header: %02X %02X %02X %02X\n  Mode: %02X\n  Temp: %02X\n  Fan: %02X\n  Reserved: %02X %02X %02X\n  Horz Swing: %02X\n  Checksum: %02X",
           d[0], d[1], d[2], d[3], d[4], d[5],
           d[6], d[7], d[8], d[9], d[10], d[11]);

  // Note: Bytes are processed in priority order, not byte order

  // Byte 0-2: Verify the header bytes are correct (static data)
  if (d[0] != VENTUSX_HEADER_B0 )
  {
    ESP_LOGV(TAG, "Invalid header received, skipped");
    return false;
  }

  if (d[1] == VENTUSX_HEADER_B1_WAKE)
  {
    ESP_LOGV(TAG, "Wake packet, skipped");
    return false;
  }

  if (d[1] != VENTUSX_HEADER_B1_DATA)
  {
    ESP_LOGV(TAG, "Unknown packet, skipped");
    return false;
  }

  // Byte 11: Checksum — sum of bytes 0–10, masked to 8 bits
  uint8_t checksum = calc_checksum(d, VENTUSX_STATE_LENGTH-1);
  if (checksum != d[11]) {
    ESP_LOGW(TAG, "Checksum mismatch: calculated 0x%02X != received 0x%02X", checksum, d[11]);
    return false;
  }

  // Byte 4: Mode
  switch (d[4] & VENTUSX_B4_MODE_MASK)
  {
    case VENTUSX_B4_MODE_HEAT:
      this->mode = climate::CLIMATE_MODE_HEAT;
      ESP_LOGV(TAG, "Decoded mode=heat from byte4=0x%02X", d[4]);
      break;
    case VENTUSX_B4_MODE_COOL:
      this->mode = climate::CLIMATE_MODE_COOL;
      ESP_LOGV(TAG, "Decoded mode=cool from byte4=0x%02X", d[4]);
      break;
    case VENTUSX_B4_MODE_DRY:
      this->mode = climate::CLIMATE_MODE_DRY;
      ESP_LOGV(TAG, "Decoded mode=dry from byte4=0x%02X", d[4]);
      break;
    case VENTUSX_B4_MODE_AUTO:
      this->mode = climate::CLIMATE_MODE_HEAT_COOL;
      ESP_LOGV(TAG, "Decoded mode=auto from byte4=0x%02X", d[4]);
      break;
    case VENTUSX_B4_MODE_FAN:
      this->mode = climate::CLIMATE_MODE_FAN_ONLY;
      ESP_LOGV(TAG, "Decoded mode=fan_only from byte4=0x%02X", d[4]);
      break;
    default:
      ESP_LOGW(TAG, "Invalid mode received from byte4=0x%02X", d[4]);
      return false;
  }

  // Byte 4: Bitmaps (no mapping in the control, so just log)
  if (d[4] & VENTUSX_B4_TURBO_BIT)
  {
    ESP_LOGV(TAG, "Decoded turbo=on from byte4=0x%02X", d[4]);
  }
  else
  {
    ESP_LOGV(TAG, "Decoded turbo=off from byte4=0x%02X", d[4]);
  }

  // Byte 3: Power (out of order so the mode is set for power)
  if (d[3] & VENTUSX_B3_BIT_UNIT_POWER)
  {
    ESP_LOGV(TAG, "Decoded unit power=on from byte3=0x%02X", d[3]);
  }
  else
  {
    ESP_LOGV(TAG, "Decoded unit power=off from byte3=0x%02X", d[3]);
    this->mode = climate::CLIMATE_MODE_OFF;
  }
  // (no mapping in the control, so just log)
  if (d[3] & VENTUSX_B3_BIT_DISPLAY_OFF)
  {
    ESP_LOGV(TAG, "Decoded display=off from byte3=0x%02X", d[3]);
  }
  else
  {
    ESP_LOGV(TAG, "Decoded display=on from byte3=0x%02X", d[3]);
  }

  // Byte 5 upper nibble → base temp (°F); byte 10 bit 0x20 → +1 for high of each pair
  static const uint8_t VENTUSX_TEMP_TABLE[16] = {
      88, 73, 81, 66, 84, 70, 77, 63,
      86, 72, 79, 64, 82, 68, 75, 61};
  uint8_t temp_f = VENTUSX_TEMP_TABLE[(d[5] >> 4) & 0xF];
  if (d[10] & 0x20) {
    temp_f++;
  }
  this->target_temperature = (temp_f - 32.0f) * 5.0f / 9.0f;  // convert °F → °C
  ESP_LOGV(TAG, "Decoded temp=%d°F (%.1f°C) from byte5=0x%02X byte10=0x%02X",
           temp_f, this->target_temperature, d[5], d[10]);
  

  // Byte 6: Fan speed (upper nibble) + vertical swing (bits 3:2)
  switch (d[6] & VENTUSX_B6_FAN_MASK)
  {
    case VENTUSX_B6_FAN_AUTO:
      this->fan_mode = climate::CLIMATE_FAN_AUTO;
      break;
    case VENTUSX_B6_FAN_LOW:
      this->fan_mode = climate::CLIMATE_FAN_LOW;
      break;
    case VENTUSX_B6_FAN_MID:
      this->fan_mode = climate::CLIMATE_FAN_MEDIUM;
      break;
    case VENTUSX_B6_FAN_HIGH:
      this->fan_mode = climate::CLIMATE_FAN_HIGH;
      break;
    default:
      ESP_LOGW(TAG, "Invalid fan mode received from byte6=0x%02X", d[6]);
      return false;
  }
  bool swing_vert = (d[6] & VENTUSX_B6_SWING_VERT_MASK) != 0;
  ESP_LOGV(TAG, "Decoded fan=0x%02X swing_vert=%d from byte6=0x%02X",
           d[6] & VENTUSX_B6_FAN_MASK, swing_vert, d[6]);

  // Byte 7-9: Reserved (ignore)

  // Byte 10: Horizontal swing (bit 0x10); temp odd-bit (0x20) already consumed above
  bool swing_horiz = (d[10] & VENTUSX_B10_SWING_HORIZ_BIT) != 0;
  if (swing_vert && swing_horiz) this->swing_mode = climate::CLIMATE_SWING_BOTH;
  else if (swing_vert)           this->swing_mode = climate::CLIMATE_SWING_VERTICAL;
  else if (swing_horiz)          this->swing_mode = climate::CLIMATE_SWING_HORIZONTAL;
  else                           this->swing_mode = climate::CLIMATE_SWING_OFF;
  ESP_LOGV(TAG, "Decoded swing_horiz=%d swing_mode=%d from byte10=0x%02X",
           swing_horiz, (int) this->swing_mode, d[10]);

  // Build and publish the final object state
  
  this->publish_state();

  return true;
}

}  // namespace mirage_ventusx
}  // namespace esphome
