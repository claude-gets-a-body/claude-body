#include "kinematics.h"

#include <math.h>

namespace kin {

static const float kPi = 3.14159265358979f;

WheelSpeeds toWheels(float v, float w, float track_m) {
  WheelSpeeds s;
  s.l = v - w * track_m * 0.5f;
  s.r = v + w * track_m * 0.5f;
  return s;
}

void toChassis(const WheelSpeeds& s, float track_m, float& v, float& w) {
  v = 0.5f * (s.l + s.r);
  w = (s.r - s.l) / track_m;
}

float mpsToSteps(float mps, float wheel_diameter_m, int steps_per_rev) {
  return mps / (kPi * wheel_diameter_m) * (float)steps_per_rev;
}

float stepsToMeters(float steps, float wheel_diameter_m, int steps_per_rev) {
  return steps / (float)steps_per_rev * (kPi * wheel_diameter_m);
}

int16_t clampSteps(float steps, int max_steps) {
  if (!(steps == steps)) return 0;  // NaN
  if (steps > (float)max_steps) steps = (float)max_steps;
  if (steps < -(float)max_steps) steps = -(float)max_steps;
  return (int16_t)lroundf(steps);
}

int32_t wrapDelta(int32_t now_raw, int32_t prev_raw, int steps_per_rev) {
  int32_t d = (now_raw - prev_raw) % steps_per_rev;
  const int32_t half = steps_per_rev / 2;
  if (d >= half) d -= steps_per_rev;
  if (d < -half) d += steps_per_rev;
  return d;
}

float wrapPi(float a) {
  while (a > kPi) a -= 2.0f * kPi;
  while (a <= -kPi) a += 2.0f * kPi;
  return a;
}

bool WheelUnwrapper::update(int32_t raw, uint32_t now_ms, uint32_t max_gap_ms,
                            int steps_per_rev, int32_t& delta_steps) {
  // Normalise anything outside 0..N-1 (sign-magnitude negatives, multi-turn).
  raw %= steps_per_rev;
  if (raw < 0) raw += steps_per_rev;
  if (!seeded_ || (uint32_t)(now_ms - last_ms_) > max_gap_ms) {
    seeded_ = true;
    last_ = raw;
    last_ms_ = now_ms;
    return false;
  }
  delta_steps = wrapDelta(raw, last_, steps_per_rev);
  last_ = raw;
  last_ms_ = now_ms;
  return true;
}

void Odometry::update(float dl, float dr, float dt) {
  const float ds = 0.5f * (dl + dr);
  const float dth = (dr - dl) / track_;
  const float mid = th + 0.5f * dth;
  x += ds * cosf(mid);
  y += ds * sinf(mid);
  th = wrapPi(th + dth);
  if (dt > 1e-4f) {
    v = ds / dt;
    w = dth / dt;
  }
}

}  // namespace kin
