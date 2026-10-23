#include "servo_cfg.h"

#include "config.h"
#include "head.h"

namespace servo {

uint16_t torqueLimit(Kind k) {
  if (k == WHEEL) return WHEEL_TORQUE_LIMIT < kWheelTorqueCeiling ? WHEEL_TORQUE_LIMIT : kWheelTorqueCeiling;
  return HEAD_TORQUE_LIMIT < kHeadTorqueCeiling ? HEAD_TORQUE_LIMIT : kHeadTorqueCeiling;
}

int eepromPlan(Kind k, RegSetting* o) {
  int n = 0;
  const bool w = (k == WHEEL);
  o[n++] = {16, 2, torqueLimit(k), "max_torque"};
  o[n++] = {28, 2, (uint16_t)(w ? WHEEL_PROT_CURRENT : HEAD_PROT_CURRENT), "prot_current"};
  o[n++] = {34, 1, (uint16_t)(w ? WHEEL_PROT_TORQUE : HEAD_PROT_TORQUE), "prot_torque"};
  o[n++] = {35, 1, (uint16_t)(w ? WHEEL_PROT_TIME : HEAD_PROT_TIME), "prot_time"};
  o[n++] = {36, 1, (uint16_t)(w ? WHEEL_OVERLOAD_TORQUE : HEAD_OVERLOAD_TORQUE), "overload_torque"};
  o[n++] = {38, 1, (uint16_t)(w ? WHEEL_PROT_TIME : HEAD_PROT_TIME), "overcurrent_time"};
  if (!w) {
    // Angle limits (regs 9 / 11, steps) = the firmware clamp range, which
    // sits 1 deg inside the tilt's mechanical stops. Works for either DIR.
    const head::Axis a = (k == PAN) ? head::panAxis() : head::tiltAxis();
    int lo = head::degToSteps(a, a.min_deg), hi = head::degToSteps(a, a.max_deg);
    if (lo > hi) {
      const int t = lo;
      lo = hi;
      hi = t;
    }
    o[n++] = {9, 2, (uint16_t)lo, "min_angle"};
    o[n++] = {11, 2, (uint16_t)hi, "max_angle"};
  }
  return n;
}

int unloadingFix(int v) {
  if (v < 0) return -1;
  const int need = 0x08 | 0x20;  // b3 current, b5 overload
  return ((v & need) == need) ? -1 : (v | need);
}

}  // namespace servo
