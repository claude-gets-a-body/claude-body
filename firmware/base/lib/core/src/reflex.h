#pragma once
// The base's reflexes (PROTOCOL 1, "Reflexes"). Hardware-free state machine:
// the main loop feeds it debounced sensor facts every control tick and applies
// the ReflexLimits it returns. Nothing here waits for the Pi.
#include <stdint.h>

#include "events.h"
#include "motion.h"

namespace reflex {

enum Fault : uint8_t {
  F_BUMP = 0,
  F_DROP,
  F_OBSTACLE,
  F_TILT,
  F_WATCHDOG,
  F_PACK_HOT,
  F_MOTORS_OFF,
  F_SERVO,  // extension: a wheel servo stopped answering
  F_COUNT
};
const char* faultName(int f);  // nullptr for "no fault"

struct Config {
  uint32_t bump_holdoff_ms;
  float reverse_max;   // m/s allowed AWAY from a bump/drop (back from a front
                       // hazard, forward from a rear drop)
  float reflex_w_max;  // rad/s turn allowed during bump/drop
  int obstacle_slow_mm, obstacle_stop_mm, obstacle_hyst_mm;
  float obstacle_slow_v;
  float tilt_limit_deg, tilt_upright_deg;
  uint32_t tilt_upright_ms;
  float pack_hot_c, pack_cool_c;
  bool ntc_fault_blocks;
  float bms_cutoff_v;
};
Config defaultConfig();  // from config.h

struct Inputs {
  uint32_t now_ms = 0;
  bool bump_l = false, bump_r = false;   // debounced
  // from tof::DropDetector. Index order kept from PROTOCOL `drop [l,c,r]`, but
  // the middle sensor is at the REAR: [0] front-left (+27 deg, r 100 mm),
  // [1] REAR (145 deg, r 95 mm), [2] front-right (-27 deg, r 100 mm).
  bool drop[3] = {true, true, true};
  int fwd_mm[2] = {-1, -1};              // tof::forwardValue (l, r)
  bool imu_ok = false;
  float roll_deg = 0, pitch_deg = 0;
  bool ntc_ok = false;
  float pack_c = 25;
  float bat_v = 0;
  bool motors_on = false;
  bool vel_fresh = false;                // a `vel` arrived < WATCHDOG_MS ago
  bool vel_ever = false;                 // any `vel` since boot
  bool wheels_ok = true;                 // both wheel servos answering
};

class Reflexes {
 public:
  explicit Reflexes(const Config& c) : c_(c) {}

  // One control tick. Pushes edge-triggered events into `ev`.
  motion::ReflexLimits update(const Inputs& in, EventQueue& ev);

  // `torque on` arrived. Returns false (and keeps servos limp) if the tilt
  // latch is set and the robot has not been upright for tilt_upright_ms.
  bool requestTorqueOn(uint32_t now_ms);

  bool tiltLatched() const { return tilt_latched_; }
  bool packHot() const { return pack_hot_; }
  bool active(int f) const { return active_[f]; }
  // Most recently activated reason that is still active, or nullptr.
  const char* fault() const;

 private:
  void setActive(int f, bool on, uint32_t now);
  int obstacleLevel(int idx, int mm);  // 0 clear, 1 slow, 2 stop

  Config c_;
  bool active_[F_COUNT] = {};
  uint32_t since_[F_COUNT] = {};
  bool last_bump_[2] = {};
  bool last_drop_[3] = {true, true, true};  // no drop events for the boot state
  uint32_t bump_until_ = 0;
  bool bump_hold_ = false;
  bool bump_pressed_ = false;
  int obst_level_[2] = {0, 0};
  bool tilt_latched_ = false;
  bool upright_ = false;
  uint32_t upright_since_ = 0;
  bool pack_hot_ = false;
  bool last_fresh_ = false;
};

}  // namespace reflex
