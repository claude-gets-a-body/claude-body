#include "motion.h"

#include <math.h>

namespace motion {

static float clampf(float x, float lo, float hi) { return x < lo ? lo : (x > hi ? hi : x); }
static float minf(float a, float b) { return a < b ? a : b; }
static bool finite(float x) { return isfinite(x); }

kin::WheelSpeeds clampToWheels(float v, float w, const Caps& caps, const ReflexLimits& lim,
                               float track_m, float wheel_v_max) {
  if (lim.block_all || !finite(v) || !finite(w)) return kin::WheelSpeeds();
  const float fwd = minf(caps.v_max, lim.v_fwd_max < 0 ? 0 : lim.v_fwd_max);
  const float rev = minf(caps.v_max, lim.v_rev_max < 0 ? 0 : lim.v_rev_max);
  const float wm = minf(caps.w_max, lim.w_max < 0 ? 0 : lim.w_max);
  v = clampf(v, -rev, fwd);
  w = clampf(w, -wm, wm);
  kin::WheelSpeeds s = kin::toWheels(v, w, track_m);
  const float peak = fmaxf(fabsf(s.l), fabsf(s.r));
  if (peak > wheel_v_max && peak > 0) {
    const float k = wheel_v_max / peak;
    s.l *= k;
    s.r *= k;
  }
  return s;
}

// Intermediate target for one wheel: if it has to reverse, stop at zero first.
static float leg(float cur, float target) {
  if ((cur > 0 && target < 0) || (cur < 0 && target > 0)) return 0;
  return target;
}

kin::WheelSpeeds ramp(const kin::WheelSpeeds& cur, const kin::WheelSpeeds& target, float a_up,
                      float a_down, float dt) {
  const float tl = leg(cur.l, target.l), tr = leg(cur.r, target.r);
  const float dl = tl - cur.l, dr = tr - cur.r;
  // allowed change per wheel this tick
  const float al = (fabsf(tl) < fabsf(cur.l) ? a_down : a_up) * dt;
  const float ar = (fabsf(tr) < fabsf(cur.r) ? a_down : a_up) * dt;
  float k = 1.0f;
  if (fabsf(dl) > al && fabsf(dl) > 0) k = fminf(k, al / fabsf(dl));
  if (fabsf(dr) > ar && fabsf(dr) > 0) k = fminf(k, ar / fabsf(dr));
  kin::WheelSpeeds out;
  out.l = (k >= 1.0f) ? tl : cur.l + dl * k;
  out.r = (k >= 1.0f) ? tr : cur.r + dr * k;
  return out;
}

Drive::Drive(const DriveConfig& cfg) : cfg_(cfg), caps_(cfg.compiled) {}

bool Drive::command(float v, float w, uint32_t now_ms) {
  if (!finite(v) || !finite(w)) return false;
  cmd_v_ = v;
  cmd_w_ = w;
  cmd_ms_ = now_ms;
  ever_ = true;
  if (fabsf(v) > 1e-4f || fabsf(w) > 1e-4f) stopped_ = at_zero_ = false;
  return true;
}

void Drive::stopNow(uint32_t now_ms) {
  cmd_v_ = cmd_w_ = 0;
  stopped_ = true;
  at_zero_ = (cur_.l == 0 && cur_.r == 0);
  zero_ms_ = now_ms;
}

Caps Drive::setLimits(float v_max, float a_max, float w_max) {
  if (finite(v_max) && v_max > 0) caps_.v_max = minf(v_max, cfg_.compiled.v_max);
  if (finite(a_max) && a_max > 0) caps_.a_max = minf(a_max, cfg_.compiled.a_max);
  if (finite(w_max) && w_max > 0) caps_.w_max = minf(w_max, cfg_.compiled.w_max);
  return caps_;
}

bool Drive::fresh(uint32_t now_ms) const {
  return ever_ && (uint32_t)(now_ms - cmd_ms_) < cfg_.watchdog_ms;
}

kin::WheelSpeeds Drive::tick(uint32_t now_ms, float dt, const ReflexLimits& lim) {
  float tv = cmd_v_, tw = cmd_w_;
  if (!fresh(now_ms)) tv = tw = 0;  // watchdog: ramp to zero at a_max
  const bool braking_stop = stopped_ && !at_zero_;
  const bool estop = lim.estop || lim.hard_stop || braking_stop;
  if (lim.block_all && !estop) {  // nothing to brake with: zero at once
    cur_ = kin::WheelSpeeds();
    return cur_;
  }
  const kin::WheelSpeeds target = clampToWheels(tv, tw, caps_, lim, cfg_.track_m, cfg_.wheel_v_max);
  if (dt < 0) dt = 0;
  if (dt > 0.1f) dt = 0.1f;  // a stalled loop must not allow a big jump
  const float a_down = estop ? fmaxf(cfg_.a_estop, caps_.a_max) : caps_.a_max;
  cur_ = ramp(cur_, target, caps_.a_max, a_down, dt);
  if (braking_stop && cur_.l == 0 && cur_.r == 0) {
    at_zero_ = true;  // `stop`: now hold zero for stop_brake_ms, then coast
    zero_ms_ = now_ms;
  }
  return cur_;
}

}  // namespace motion
