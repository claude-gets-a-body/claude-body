#include "head.h"

#include <math.h>

#include "config.h"

namespace head {

static const float kStepsPerDeg = (float)STS_STEPS_PER_REV / 360.0f;

Axis panAxis() { return Axis{PAN_MIN_DEG, PAN_MAX_DEG, PAN_CENTER_STEPS, PAN_DIR}; }
Axis tiltAxis() { return Axis{TILT_MIN_DEG, TILT_MAX_DEG, TILT_CENTER_STEPS, TILT_DIR}; }

float clampDeg(const Axis& a, float deg) {
  if (!(deg == deg)) return 0;
  if (deg < a.min_deg) return a.min_deg;
  if (deg > a.max_deg) return a.max_deg;
  return deg;
}

int degToSteps(const Axis& a, float deg) {
  deg = clampDeg(a, deg);
  int s = a.center_steps + (int)lroundf(deg * kStepsPerDeg * (float)a.dir);
  if (s < 0) s = 0;
  if (s > STS_STEPS_PER_REV - 1) s = STS_STEPS_PER_REV - 1;
  return s;
}

float stepsToDeg(const Axis& a, int steps) {
  return (float)(steps - a.center_steps) / kStepsPerDeg * (float)a.dir;
}

int speedToSteps(float dps, float max_dps, float default_dps) {
  if (!(dps == dps) || dps <= 0) dps = default_dps;
  if (dps > max_dps) dps = max_dps;
  int s = (int)lroundf(dps * kStepsPerDeg);
  return s < 1 ? 1 : s;
}

}  // namespace head
