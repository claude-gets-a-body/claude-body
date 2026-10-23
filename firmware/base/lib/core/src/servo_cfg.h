#pragma once
// What the base writes into each STS3215's EEPROM at bring-up (only when a
// value differs) and then reads back. Hardware-free so the safety ceilings
// and the angle limits are unit-tested.
#include <stdint.h>

namespace servo {

enum Kind : uint8_t { WHEEL = 0, PAN, TILT };

struct RegSetting {
  uint8_t reg;       // ST3215 memory table V3.7 address
  uint8_t size;      // bytes (2 = little-endian word)
  uint16_t value;
  const char* name;  // for servo_error details
};

// Hard ceilings (DESIGN 5 + review): wheels <= 30 %, pan/tilt <= 10 %.
static const uint16_t kWheelTorqueCeiling = 300;
static const uint16_t kHeadTorqueCeiling = 100;

// Fills `out` (room for at least 8) and returns the count.
int eepromPlan(Kind k, RegSetting* out);

// SRAM torque limit (reg 48) for this kind, already clamped to the ceiling.
uint16_t torqueLimit(Kind k);

// Unloading conditions (reg 19): current (bit 3) and overload (bit 5)
// protection must be on. Returns the value to write, or -1 if already fine.
int unloadingFix(int current_value);

}  // namespace servo
