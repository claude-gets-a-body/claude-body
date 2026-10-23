#pragma once
// Differential-drive kinematics, servo unit conversion and wheel odometry.
// Hardware-free (unit-tested on the host).
#include <stdint.h>

namespace kin {

struct WheelSpeeds {
  float l = 0;  // m/s at the tyre, + = robot forward
  float r = 0;
};

// Chassis (v m/s, w rad/s, + = counter-clockwise / left turn) -> wheel speeds.
WheelSpeeds toWheels(float v, float w, float track_m);
void toChassis(const WheelSpeeds& s, float track_m, float& v, float& w);

// Tyre speed (m/s) -> servo steps/s and back.
float mpsToSteps(float mps, float wheel_diameter_m, int steps_per_rev);
float stepsToMeters(float steps, float wheel_diameter_m, int steps_per_rev);

// Round and clamp a steps/s value to +-max_steps (for the goal-speed register).
int16_t clampSteps(float steps, int max_steps);

// Shortest signed difference between two raw positions on a 0..steps_per_rev-1
// circle, e.g. (5, 4090) -> +11 with 4096 steps.
int32_t wrapDelta(int32_t now_raw, int32_t prev_raw, int steps_per_rev);

// Normalise an angle to (-pi, pi].
float wrapPi(float a);

// Turns successive raw 0..4095 positions of one wheel into a continuous count.
// A gap longer than max_gap_ms between good readings (e.g. the servo stopped
// answering) re-seeds instead of trusting a delta that may have wrapped twice.
class WheelUnwrapper {
 public:
  void reset() { seeded_ = false; }
  // Returns true and sets delta_steps when a usable delta exists.
  bool update(int32_t raw, uint32_t now_ms, uint32_t max_gap_ms, int steps_per_rev,
              int32_t& delta_steps);
  bool seeded() const { return seeded_; }

 private:
  bool seeded_ = false;
  int32_t last_ = 0;
  uint32_t last_ms_ = 0;
};

// Integrates wheel travel into a pose. Midpoint integration.
class Odometry {
 public:
  explicit Odometry(float track_m) : track_(track_m) {}
  void reset() { x = y = th = v = w = 0; }
  // dl, dr: metres travelled by each tyre since the last call; dt seconds.
  void update(float dl, float dr, float dt);
  float x = 0, y = 0, th = 0;  // m, m, rad
  float v = 0, w = 0;          // m/s, rad/s (last update)

 private:
  float track_;
};

}  // namespace kin
