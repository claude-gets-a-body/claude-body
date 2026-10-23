#include <math.h>
#include <stdio.h>
#include <unity.h>

#include "config.h"
#include "motion.h"

using namespace motion;

static DriveConfig cfg() {
  DriveConfig c;
  c.compiled = Caps{CAP_V_MAX, CAP_W_MAX, CAP_A_MAX};
  c.track_m = TRACK_WIDTH_M;
  c.wheel_v_max = CAP_WHEEL_V_MAX;
  c.watchdog_ms = WATCHDOG_MS;
  c.stop_brake_ms = STOP_BRAKE_MS;
  c.a_estop = A_ESTOP;
  return c;
}
static const float DT = CONTROL_PERIOD_MS / 1000.0f;

void setUp() {}
void tearDown() {}

void test_compiled_caps() {
  TEST_ASSERT_EQUAL_FLOAT(0.25f, CAP_V_MAX);
  TEST_ASSERT_EQUAL_FLOAT(1.5f, CAP_W_MAX);
  TEST_ASSERT_EQUAL_FLOAT(0.5f, CAP_A_MAX);
  TEST_ASSERT_EQUAL(300, WATCHDOG_MS);
}

void test_speed_capped_and_ramped() {
  Drive d(cfg());
  ReflexLimits none;
  uint32_t t = 0;
  kin::WheelSpeeds s;
  int ticks_to_cap = -1;
  for (int i = 0; i < 60; i++) {
    t += 20;
    d.command(1.0f, 0, t);  // asks for 4x the cap
    s = d.tick(t, DT, none);
    TEST_ASSERT_TRUE(s.l <= CAP_V_MAX + 1e-6f);
    if (ticks_to_cap < 0 && fabsf(s.l - CAP_V_MAX) < 1e-5f) ticks_to_cap = i + 1;
  }
  // 0 -> 0.25 m/s at 0.5 m/s^2 = 0.5 s = 25 ticks of 20 ms
  TEST_ASSERT_EQUAL(25, ticks_to_cap);
}

void test_per_wheel_accel_never_exceeds_cap() {
  Drive d(cfg());
  ReflexLimits none;
  uint32_t t = 0;
  kin::WheelSpeeds prev;
  const float cmds[][2] = {{0.25f, 1.5f}, {-0.25f, -1.5f}, {0, 1.5f}, {0.2f, -1.0f}, {0, 0}};
  for (auto& c : cmds) {
    for (int i = 0; i < 40; i++) {
      t += 20;
      d.command(c[0], c[1], t);
      kin::WheelSpeeds s = d.tick(t, DT, none);
      TEST_ASSERT_TRUE(fabsf(s.l - prev.l) <= CAP_A_MAX * DT + 1e-5f);
      TEST_ASSERT_TRUE(fabsf(s.r - prev.r) <= CAP_A_MAX * DT + 1e-5f);
      TEST_ASSERT_TRUE(fabsf(s.l) <= CAP_WHEEL_V_MAX + 1e-5f);
      TEST_ASSERT_TRUE(fabsf(s.r) <= CAP_WHEEL_V_MAX + 1e-5f);
      prev = s;
    }
  }
}

void test_ramp_keeps_curvature() {
  Drive d(cfg());
  ReflexLimits none;
  uint32_t t = 0;
  for (int i = 0; i < 10; i++) {
    t += 20;
    d.command(0.2f, 1.0f, t);
    kin::WheelSpeeds s = d.tick(t, DT, none);
    kin::WheelSpeeds target = kin::toWheels(0.2f, 1.0f, TRACK_WIDTH_M);
    TEST_ASSERT_FLOAT_WITHIN(1e-4, target.l / target.r, s.l / s.r);
  }
}

void test_wheel_saturation_scales_both() {
  Caps caps{CAP_V_MAX, CAP_W_MAX, CAP_A_MAX};
  ReflexLimits none;
  kin::WheelSpeeds s = clampToWheels(0.25f, 1.5f, caps, none, TRACK_WIDTH_M, CAP_WHEEL_V_MAX);
  TEST_ASSERT_FLOAT_WITHIN(1e-5, CAP_WHEEL_V_MAX, fmaxf(fabsf(s.l), fabsf(s.r)));
  kin::WheelSpeeds raw = kin::toWheels(0.25f, 1.5f, TRACK_WIDTH_M);
  TEST_ASSERT_FLOAT_WITHIN(1e-4, raw.l / raw.r, s.l / s.r);
}

void test_watchdog_ramps_to_zero() {
  Drive d(cfg());
  ReflexLimits none;
  uint32_t t = 0;
  for (int i = 0; i < 40; i++) {
    t += 20;
    d.command(0.2f, 0, t);
    d.tick(t, DT, none);
  }
  const uint32_t last_cmd = t;
  TEST_ASSERT_FLOAT_WITHIN(1e-5, 0.2f, d.current().l);
  // keep ticking with no command
  float prev = d.current().l;
  bool stopped = false;
  for (int i = 0; i < 60; i++) {
    t += 20;
    kin::WheelSpeeds s = d.tick(t, DT, none);
    if (t - last_cmd < WATCHDOG_MS) {
      TEST_ASSERT_FLOAT_WITHIN(1e-5, 0.2f, s.l);  // still fresh
    } else {
      TEST_ASSERT_FALSE(d.fresh(t));
      TEST_ASSERT_TRUE(prev - s.l <= CAP_A_MAX * DT + 1e-5f);  // ramped, not slammed
    }
    if (s.l == 0) stopped = true;
    prev = s.l;
  }
  TEST_ASSERT_TRUE(stopped);
}

// drive at 0.25 m/s, steady
static uint32_t cruise(Drive& d, float v) {
  ReflexLimits none;
  uint32_t t = 0;
  for (int i = 0; i < 60; i++) {
    t += 20;
    d.command(v, 0, t);
    d.tick(t, DT, none);
  }
  return t;
}

static ReflexLimits frontHazard(bool onset) {
  ReflexLimits l;
  l.hard_stop = onset;
  l.estop = true;
  l.v_fwd_max = 0;
  l.v_rev_max = REFLEX_REVERSE_MAX;
  l.w_max = REFLEX_W_MAX;
  return l;
}

void test_estop_stop_distance_under_25mm() {
  TEST_ASSERT_EQUAL_FLOAT(1.5f, A_ESTOP);
  Drive d(cfg());
  uint32_t t = cruise(d, 0.25f);
  TEST_ASSERT_FLOAT_WITHIN(1e-5, 0.25f, d.current().l);
  // trigger on this tick; the Pi keeps asking for full speed throughout
  float travel = 0;
  int ticks = 0;
  for (int i = 0; i < 50; i++) {
    t += 20;
    d.command(0.25f, 0, t);
    const kin::WheelSpeeds s = d.tick(t, DT, frontHazard(i == 0));
    travel += 0.5f * (s.l + s.r) * DT;  // speed sent this tick, held for one period
    if (s.l == 0 && s.r == 0) break;
    ticks++;
    // never faster than A_ESTOP allows, never backwards while stopping
    TEST_ASSERT_TRUE(s.l >= 0);
  }
  char msg[80];
  snprintf(msg, sizeof msg, "stop from 0.25 m/s: %.1f mm in %d ticks of 20 ms", travel * 1000, ticks);
  TEST_MESSAGE(msg);
  TEST_ASSERT_TRUE_MESSAGE(travel < 0.025f, "stop distance >= 25 mm");
  TEST_ASSERT_TRUE(travel > 0.010f);  // and it is a brake, not a slam
  TEST_ASSERT_TRUE(ticks <= 9);       // ~0.17 s
}

void test_estop_decel_rate_and_reverse_after() {
  Drive d(cfg());
  uint32_t t = cruise(d, 0.25f);
  float prev = d.current().l;
  for (int i = 0; i < 30; i++) {
    t += 20;
    d.command(-0.25f, 0, t);  // Pi asks to back away hard
    const kin::WheelSpeeds s = d.tick(t, DT, frontHazard(i == 0));
    const float dv = s.l - prev;
    if (prev > 0) {
      // braking: exactly A_ESTOP per tick until zero, never past zero in one go
      TEST_ASSERT_TRUE(dv >= -A_ESTOP * DT - 1e-5f);
      if (s.l > 0) TEST_ASSERT_FLOAT_WITHIN(1e-5, -A_ESTOP * DT, dv);
      TEST_ASSERT_TRUE(s.l >= 0);
    } else {
      // speeding up the other way: only a_max
      TEST_ASSERT_TRUE(fabsf(dv) <= CAP_A_MAX * DT + 1e-5f);
    }
    prev = s.l;
  }
  TEST_ASSERT_FLOAT_WITHIN(1e-5, -REFLEX_REVERSE_MAX, prev);  // reverse capped at 0.08
}

void test_watchdog_uses_a_max_not_estop() {
  Drive d(cfg());
  uint32_t t = cruise(d, 0.25f);
  ReflexLimits none;
  float prev = d.current().l;
  t += WATCHDOG_MS;  // stream stopped
  for (int i = 0; i < 40; i++) {
    t += 20;
    const kin::WheelSpeeds s = d.tick(t, DT, none);
    TEST_ASSERT_TRUE(prev - s.l <= CAP_A_MAX * DT + 1e-5f);
    prev = s.l;
  }
  TEST_ASSERT_EQUAL_FLOAT(0, prev);
}

void test_block_all_with_estop_brakes_without_snaps_to_zero() {
  // tilt / pack hot: block_all + estop -> braked; motors off / servo lost: zero at once
  Drive d(cfg());
  uint32_t t = cruise(d, 0.25f);
  ReflexLimits tilt;
  tilt.block_all = tilt.estop = true;
  t += 20;
  kin::WheelSpeeds s = d.tick(t, DT, tilt);
  TEST_ASSERT_FLOAT_WITHIN(1e-5, 0.25f - A_ESTOP * DT, s.l);
  ReflexLimits dead;
  dead.block_all = true;
  t += 20;
  s = d.tick(t, DT, dead);
  TEST_ASSERT_EQUAL_FLOAT(0, s.l);
}

void test_rear_drop_limits_in_drive() {
  // rear drop: reverse refused (braked at A_ESTOP, never pushed further back),
  // forward creeps at <= 0.08, spin still possible
  Drive d(cfg());
  uint32_t t = cruise(d, -0.2f);
  TEST_ASSERT_FLOAT_WITHIN(1e-5, -0.2f, d.current().l);
  ReflexLimits rear;
  rear.hard_stop = true;
  rear.estop = true;
  rear.v_rev_max = 0;
  rear.v_fwd_max = REFLEX_REVERSE_MAX;
  rear.w_max = REFLEX_W_MAX;
  float travel = 0, prev = d.current().l;
  for (int i = 0; i < 40; i++) {
    t += 20;
    d.command(-0.2f, 0, t);
    const kin::WheelSpeeds s = d.tick(t, DT, rear);
    rear.hard_stop = false;
    travel += s.l * DT;
    TEST_ASSERT_TRUE(s.l >= prev - 1e-6f);  // only ever slowing the reverse
    TEST_ASSERT_TRUE(s.l <= 0);
    prev = s.l;
  }
  TEST_ASSERT_EQUAL_FLOAT(0, prev);
  TEST_ASSERT_TRUE(travel > -0.025f);
  kin::WheelSpeeds s;
  for (int i = 0; i < 40; i++) {
    t += 20;
    d.command(0.25f, 0, t);
    s = d.tick(t, DT, rear);
  }
  TEST_ASSERT_FLOAT_WITHIN(1e-5, REFLEX_REVERSE_MAX, s.l);
  for (int i = 0; i < 60; i++) {  // spin on the spot, capped
    t += 20;
    d.command(0, 1.5f, t);
    s = d.tick(t, DT, rear);
  }
  float v, w;
  kin::toChassis(s, TRACK_WIDTH_M, v, w);
  TEST_ASSERT_FLOAT_WITHIN(1e-4, REFLEX_W_MAX, w);
  TEST_ASSERT_FLOAT_WITHIN(1e-5, 0, v);
}

void test_slow_zone_reduction_uses_a_max() {
  // obstacle < 120 mm (not an emergency): slowed at a_max down to 0.05
  Drive d(cfg());
  uint32_t t = cruise(d, 0.25f);
  ReflexLimits slow;
  slow.v_fwd_max = OBSTACLE_SLOW_V;
  float prev = d.current().l;
  for (int i = 0; i < 40; i++) {
    t += 20;
    d.command(0.25f, 0, t);
    const kin::WheelSpeeds s = d.tick(t, DT, slow);
    TEST_ASSERT_TRUE(prev - s.l <= CAP_A_MAX * DT + 1e-5f);
    prev = s.l;
  }
  TEST_ASSERT_FLOAT_WITHIN(1e-5, OBSTACLE_SLOW_V, prev);
}

void test_block_all() {
  Drive d(cfg());
  ReflexLimits block;
  block.block_all = true;
  uint32_t t = 20;
  d.command(0.25f, 1.0f, t);
  kin::WheelSpeeds s = d.tick(t, DT, block);
  TEST_ASSERT_EQUAL_FLOAT(0, s.l);
  TEST_ASSERT_EQUAL_FLOAT(0, s.r);
}

void test_limits_only_lower() {
  Drive d(cfg());
  Caps c = d.setLimits(1.0f, 9.0f, 9.0f);  // cannot raise
  TEST_ASSERT_EQUAL_FLOAT(CAP_V_MAX, c.v_max);
  TEST_ASSERT_EQUAL_FLOAT(CAP_A_MAX, c.a_max);
  TEST_ASSERT_EQUAL_FLOAT(CAP_W_MAX, c.w_max);
  c = d.setLimits(0.1f, NAN, -1.0f);  // lower v, ignore the others
  TEST_ASSERT_EQUAL_FLOAT(0.1f, c.v_max);
  TEST_ASSERT_EQUAL_FLOAT(CAP_A_MAX, c.a_max);
  TEST_ASSERT_EQUAL_FLOAT(CAP_W_MAX, c.w_max);
  c = d.setLimits(0.2f, NAN, NAN);  // back up, but never above compiled
  TEST_ASSERT_EQUAL_FLOAT(0.2f, c.v_max);
  ReflexLimits none;
  uint32_t t = 0;
  d.setLimits(0.1f, NAN, NAN);
  for (int i = 0; i < 50; i++) {
    t += 20;
    d.command(0.25f, 0, t);
    d.tick(t, DT, none);
  }
  TEST_ASSERT_FLOAT_WITHIN(1e-5, 0.1f, d.current().l);
}

void test_stop_brakes_then_coasts_until_new_motion() {
  Drive d(cfg());
  ReflexLimits none;
  uint32_t t = cruise(d, 0.2f);
  d.stopNow(t);
  // brakes at A_ESTOP (not a slam, not a_max), torque held all the while
  float prev = d.current().l;
  uint32_t zero_at = 0;
  for (int i = 0; i < 30; i++) {
    t += 20;
    d.command(0, 0, t);  // stream of zero vel keeps it stopped
    const kin::WheelSpeeds s = d.tick(t, DT, none);
    TEST_ASSERT_TRUE(prev - s.l <= A_ESTOP * DT + 1e-5f);
    if (prev > 0 && s.l > 0) TEST_ASSERT_TRUE(prev - s.l > CAP_A_MAX * DT);
    if (s.l == 0 && !zero_at) zero_at = t;
    if (!zero_at || t - zero_at < STOP_BRAKE_MS) TEST_ASSERT_TRUE(d.wheelTorqueWanted(t));
    else TEST_ASSERT_FALSE(d.wheelTorqueWanted(t));  // then coast
    prev = s.l;
  }
  TEST_ASSERT_TRUE(zero_at > 0);
  d.command(0.05f, 0, t);  // new motion re-enables torque
  TEST_ASSERT_TRUE(d.wheelTorqueWanted(t));
}

void test_stop_when_already_still() {
  Drive d(cfg());
  d.stopNow(1000);
  TEST_ASSERT_TRUE(d.wheelTorqueWanted(1000 + STOP_BRAKE_MS - 1));
  TEST_ASSERT_FALSE(d.wheelTorqueWanted(1000 + STOP_BRAKE_MS));
}

void test_rejects_non_finite() {
  Drive d(cfg());
  TEST_ASSERT_FALSE(d.command(NAN, 0, 10));
  TEST_ASSERT_FALSE(d.command(0, INFINITY, 10));
  TEST_ASSERT_FALSE(d.everCommanded());
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_compiled_caps);
  RUN_TEST(test_speed_capped_and_ramped);
  RUN_TEST(test_per_wheel_accel_never_exceeds_cap);
  RUN_TEST(test_ramp_keeps_curvature);
  RUN_TEST(test_wheel_saturation_scales_both);
  RUN_TEST(test_watchdog_ramps_to_zero);
  RUN_TEST(test_estop_stop_distance_under_25mm);
  RUN_TEST(test_estop_decel_rate_and_reverse_after);
  RUN_TEST(test_watchdog_uses_a_max_not_estop);
  RUN_TEST(test_block_all_with_estop_brakes_without_snaps_to_zero);
  RUN_TEST(test_rear_drop_limits_in_drive);
  RUN_TEST(test_slow_zone_reduction_uses_a_max);
  RUN_TEST(test_block_all);
  RUN_TEST(test_limits_only_lower);
  RUN_TEST(test_stop_brakes_then_coasts_until_new_motion);
  RUN_TEST(test_stop_when_already_still);
  RUN_TEST(test_rejects_non_finite);
  return UNITY_END();
}
