#pragma once
// Speed / acceleration governor for the drive wheels. Hardware-free.
//
// Rules (PROTOCOL 1):
//  * targets are clamped to the runtime caps (which can only be LOWER than the
//    compiled-in caps) and to whatever the reflexes currently allow;
//  * speeding up is always ramped at a_max per wheel (both wheels scaled
//    together so the path's curvature is kept while ramping);
//  * slowing down is ramped at a_max normally (incl. the watchdog), but at
//    a_estop during an emergency (bump, drop, tilt, obstacle < 60 mm, pack
//    hot, `stop`) -- hard enough to stop short, soft enough not to tip;
//  * no power to brake with (motors off, servo comms lost) -> zero at once;
//  * no `vel` for WATCHDOG_MS -> target becomes zero, reached at a_max.
#include <stdint.h>

#include "kinematics.h"

namespace motion {

struct Caps {
  float v_max, w_max, a_max;
};

// What the reflex layer allows right now.
struct ReflexLimits {
  float v_fwd_max = 1e9f;  // forward speed allowed (0 = no forward motion)
  float v_rev_max = 1e9f;  // reverse speed magnitude allowed
  float w_max = 1e9f;      // turn rate magnitude allowed
  bool hard_stop = false;  // a reflex fired this tick (onset; implies estop)
  bool estop = false;      // an emergency reflex is active: brake at a_estop
  bool block_all = false;  // no motion at all (tilt, pack hot, motors off, servo).
                           // With estop: braked to zero; without: zero at once.
  bool torque_kill = false;  // tilt: servos must go limp
};

// Clamp (v, w) to caps and reflex limits, convert to wheels and scale both
// wheels down together if either exceeds wheel_v_max.
kin::WheelSpeeds clampToWheels(float v, float w, const Caps& caps,
                               const ReflexLimits& lim, float track_m, float wheel_v_max);

// Move `cur` towards `target`. Per wheel, a change that reduces |speed|
// (towards zero) may be up to a_down*dt, an increase up to a_up*dt; both
// wheels are scaled by the same factor so they arrive together. A wheel that
// must change direction first stops at zero (braking), then speeds up the
// other way on later ticks.
kin::WheelSpeeds ramp(const kin::WheelSpeeds& cur, const kin::WheelSpeeds& target, float a_up,
                      float a_down, float dt);

struct DriveConfig {
  Caps compiled;
  float track_m;
  float wheel_v_max;
  uint32_t watchdog_ms;
  uint32_t stop_brake_ms;  // `stop`: hold zero with torque this long, then coast
  float a_estop;           // emergency deceleration, m/s^2
};

class Drive {
 public:
  explicit Drive(const DriveConfig& cfg);

  // `vel` message. Non-finite values are rejected (returns false).
  bool command(float v, float w, uint32_t now_ms);
  // `stop` message: brake to zero at a_estop, hold zero with torque for
  // stop_brake_ms, then wheels go torque-off (coast) until the next non-zero `vel`.
  void stopNow(uint32_t now_ms);
  // `limits` message. Each value <= 0 or non-finite is ignored; others are
  // clamped to the compiled caps. Returns the resulting caps.
  Caps setLimits(float v_max, float a_max, float w_max);
  Caps caps() const { return caps_; }
  Caps compiledCaps() const { return cfg_.compiled; }

  bool fresh(uint32_t now_ms) const;
  bool everCommanded() const { return ever_; }
  bool wheelTorqueWanted(uint32_t now_ms) const {
    if (!stopped_ || !at_zero_) return true;  // still braking
    return (uint32_t)(now_ms - zero_ms_) < cfg_.stop_brake_ms;
  }

  // Advance one control tick. Returns the wheel speeds to send.
  kin::WheelSpeeds tick(uint32_t now_ms, float dt, const ReflexLimits& lim);
  kin::WheelSpeeds current() const { return cur_; }

 private:
  DriveConfig cfg_;
  Caps caps_;
  float cmd_v_ = 0, cmd_w_ = 0;
  uint32_t cmd_ms_ = 0;
  bool ever_ = false;
  bool stopped_ = false;   // `stop` received, no motion command since
  bool at_zero_ = false;   // ... and the wheels have reached zero
  uint32_t zero_ms_ = 0;
  kin::WheelSpeeds cur_;
};

}  // namespace motion
