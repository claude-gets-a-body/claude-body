#include "reflex.h"

#include <math.h>
#include <stdio.h>

#include "config.h"

namespace reflex {

static const char* const kFaultNames[F_COUNT] = {
    "bump", "drop", "obstacle", "tilt", "watchdog", "pack_hot", "motors_off", "servo_error"};

const char* faultName(int f) { return (f >= 0 && f < F_COUNT) ? kFaultNames[f] : nullptr; }

Config defaultConfig() {
  Config c;
  c.bump_holdoff_ms = BUMP_HOLDOFF_MS;
  c.reverse_max = REFLEX_REVERSE_MAX;
  c.reflex_w_max = REFLEX_W_MAX;
  c.obstacle_slow_mm = OBSTACLE_SLOW_MM;
  c.obstacle_stop_mm = OBSTACLE_STOP_MM;
  c.obstacle_hyst_mm = OBSTACLE_HYST_MM;
  c.obstacle_slow_v = OBSTACLE_SLOW_V;
  c.tilt_limit_deg = TILT_LIMIT_DEG;
  c.tilt_upright_deg = TILT_UPRIGHT_DEG;
  c.tilt_upright_ms = TILT_UPRIGHT_MS;
  c.pack_hot_c = PACK_HOT_C;
  c.pack_cool_c = PACK_COOL_C;
  c.ntc_fault_blocks = NTC_FAULT_BLOCKS_MOTION != 0;
  c.bms_cutoff_v = BMS_CUTOFF_V;
  return c;
}

void Reflexes::setActive(int f, bool on, uint32_t now) {
  if (on && !active_[f]) since_[f] = now;
  active_[f] = on;
}

const char* Reflexes::fault() const {
  int best = -1;
  for (int f = 0; f < F_COUNT; f++) {
    if (!active_[f]) continue;
    // ">=" so that on a tie the later (more severe) entry in the enum wins
    if (best < 0 || (int32_t)(since_[f] - since_[best]) >= 0) best = f;
  }
  return best < 0 ? nullptr : kFaultNames[best];
}

int Reflexes::obstacleLevel(int idx, int mm) {
  int& lvl = obst_level_[idx];
  if (mm < 0) {  // no usable reading: degrade to "slow"
    lvl = lvl > 1 ? lvl : 1;
    return lvl;
  }
  const int h = c_.obstacle_hyst_mm;
  if (mm < c_.obstacle_stop_mm) lvl = 2;
  else if (lvl == 2 && mm < c_.obstacle_stop_mm + h) lvl = 2;
  else if (mm < c_.obstacle_slow_mm) lvl = 1;
  else if (lvl >= 1 && mm < c_.obstacle_slow_mm + h) lvl = 1;
  else lvl = 0;
  return lvl;
}

bool Reflexes::requestTorqueOn(uint32_t now_ms) {
  if (!tilt_latched_) return true;
  if (upright_ && (uint32_t)(now_ms - upright_since_) >= c_.tilt_upright_ms) {
    tilt_latched_ = false;
    setActive(F_TILT, false, now_ms);
    return true;
  }
  return false;
}

motion::ReflexLimits Reflexes::update(const Inputs& in, EventQueue& ev) {
  motion::ReflexLimits lim;
  const uint32_t now = in.now_ms;

  // ---- Bump: stop at once; no forward while pressed and for holdoff after.
  static const char* const kBumpEv[2] = {"bump_l", "bump_r"};
  const bool bumps[2] = {in.bump_l, in.bump_r};
  bool any_bump = false;
  for (int i = 0; i < 2; i++) {
    if (bumps[i] && !last_bump_[i]) {
      ev.push(kBumpEv[i]);
      lim.hard_stop = true;
    }
    last_bump_[i] = bumps[i];
    any_bump |= bumps[i];
  }
  if (any_bump) {
    bump_hold_ = true;
    bump_pressed_ = true;
  } else if (bump_pressed_) {
    // released now: hold off forward motion for holdoff_ms from this moment
    bump_pressed_ = false;
    bump_until_ = now + c_.bump_holdoff_ms;
  } else if (bump_hold_ && (int32_t)(now - bump_until_) >= 0) {
    bump_hold_ = false;
  }
  setActive(F_BUMP, bump_hold_, now);

  // ---- Drop: stop at once. Index 1 is the REAR sensor (the robot reverses
  //      onto its dock): a front drop blocks forward, a rear drop blocks reverse.
  static const char* const kDropEv[3] = {"drop_l", "drop_rear", "drop_r"};
  bool any_drop = false;
  for (int i = 0; i < 3; i++) {
    if (in.drop[i] && !last_drop_[i]) {
      ev.push(kDropEv[i]);
      lim.hard_stop = true;
    }
    last_drop_[i] = in.drop[i];
    any_drop |= in.drop[i];
  }
  setActive(F_DROP, any_drop, now);

  // Front hazards (bumper is front-only, drop sensors 0 and 2): no forward,
  // back away at <= reverse_max. Rear hazard (drop sensor 1): no reverse,
  // pull away forwards at <= reverse_max. Both: no linear motion at all.
  // Turning on the spot stays allowed at <= reflex_w_max in every case.
  const bool front_block = bump_hold_ || in.drop[0] || in.drop[2];
  const bool rear_block = in.drop[1];
  if (front_block || rear_block) lim.w_max = c_.reflex_w_max;
  if (front_block) {
    lim.v_fwd_max = 0;
    lim.v_rev_max = rear_block ? 0 : c_.reverse_max;
  }
  if (rear_block) {
    lim.v_rev_max = 0;
    lim.v_fwd_max = front_block ? 0 : c_.reverse_max;
  }

  // ---- Obstacle: < slow_mm -> cap forward; < stop_mm -> no forward.
  int worst = 0, worst_idx = 0;
  for (int i = 0; i < 2; i++) {
    const int before = obst_level_[i];
    const int lvl = obstacleLevel(i, in.fwd_mm[i]);
    if (lvl > 0 && before == 0) {
      char d[24];
      if (in.fwd_mm[i] < 0) snprintf(d, sizeof d, "%s sensor_fault", i ? "r" : "l");
      else snprintf(d, sizeof d, "%s %dmm", i ? "r" : "l", in.fwd_mm[i]);
      ev.push("obstacle", d);
    }
    if (lvl > worst) {
      worst = lvl;
      worst_idx = i;
    }
  }
  (void)worst_idx;
  if (worst == 1 && lim.v_fwd_max > c_.obstacle_slow_v) lim.v_fwd_max = c_.obstacle_slow_v;
  if (worst == 2) {
    lim.v_fwd_max = 0;
    lim.estop = true;  // < stop distance: emergency brake
  }
  setActive(F_OBSTACLE, worst > 0, now);

  // ---- Tilt: torque off on everything; latched until upright for
  //      tilt_upright_ms AND a `torque on` (requestTorqueOn).
  const float ar = fabsf(in.roll_deg), ap = fabsf(in.pitch_deg);
  const bool tilted = !in.imu_ok || ar > c_.tilt_limit_deg || ap > c_.tilt_limit_deg;
  const bool upright = in.imu_ok && ar < c_.tilt_upright_deg && ap < c_.tilt_upright_deg;
  if (tilted && !tilt_latched_) {
    tilt_latched_ = true;
    ev.push("tilt", in.imu_ok ? "" : "imu_fault");
  }
  if (upright && !upright_) upright_since_ = now;
  upright_ = upright;
  setActive(F_TILT, tilt_latched_, now);
  if (tilt_latched_) {
    lim.block_all = true;
    lim.torque_kill = true;
  }

  // ---- Pack over temperature / NTC fault / BMS cut-off.
  const bool ntc_bad = !in.ntc_ok && c_.ntc_fault_blocks;
  const bool bms_cut = in.bat_v < c_.bms_cutoff_v;
  const bool hot = (in.ntc_ok && in.pack_c > c_.pack_hot_c) || ntc_bad || bms_cut;
  if (hot && !pack_hot_) {
    pack_hot_ = true;
    lim.hard_stop = true;
    ev.push("pack_hot", bms_cut ? "bms_cutoff" : (ntc_bad ? "ntc_fault" : "temp"));
  } else if (pack_hot_ && !hot && (!in.ntc_ok || in.pack_c < c_.pack_cool_c)) {
    pack_hot_ = false;
  }
  setActive(F_PACK_HOT, pack_hot_, now);
  if (pack_hot_) lim.block_all = true;

  // ---- Motor kill switch.
  // Emergency reflexes brake at a_estop (the slow zone and the watchdog use a_max).
  if (bump_hold_ || any_drop || tilt_latched_ || pack_hot_) lim.estop = true;
  if (lim.hard_stop) lim.estop = true;

  setActive(F_MOTORS_OFF, !in.motors_on, now);
  if (!in.motors_on) lim.block_all = true;

  // ---- Wheel servos not answering.
  setActive(F_SERVO, !in.wheels_ok, now);
  if (!in.wheels_ok) lim.block_all = true;

  // ---- Watchdog: the Drive ramps to zero on its own; here we report it.
  if (last_fresh_ && !in.vel_fresh && in.vel_ever) ev.push("watchdog");
  last_fresh_ = in.vel_fresh;
  setActive(F_WATCHDOG, !in.vel_fresh, now);

  return lim;
}

}  // namespace reflex
