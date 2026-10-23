#pragma once
// Neck pan / head tilt conversions and limits. Hardware-free.
#include <stdint.h>

namespace head {

struct Axis {
  float min_deg, max_deg;
  int center_steps;  // servo position at 0 deg
  int dir;           // +1 or -1
};

Axis panAxis();   // from config.h
Axis tiltAxis();

float clampDeg(const Axis& a, float deg);
int degToSteps(const Axis& a, float deg);         // clamps first
float stepsToDeg(const Axis& a, int steps);
// deg/s -> steps/s for the goal-speed register, clamped to 1..max_dps.
// (0 means "maximum speed" to the servo, so it is never sent.)
int speedToSteps(float dps, float max_dps, float default_dps);

}  // namespace head
