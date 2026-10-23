#include <math.h>
#include <unity.h>

#include "config.h"
#include "kinematics.h"

using namespace kin;

void setUp() {}
void tearDown() {}

static const float PI_F = 3.14159265f;

void test_config_constants() {
  TEST_ASSERT_EQUAL_FLOAT(0.100f, WHEEL_DIAMETER_M);
  TEST_ASSERT_EQUAL_FLOAT(0.172f, TRACK_WIDTH_M);
}

void test_to_wheels_straight_and_spin() {
  WheelSpeeds s = toWheels(0.2f, 0, TRACK_WIDTH_M);
  TEST_ASSERT_FLOAT_WITHIN(1e-6, 0.2f, s.l);
  TEST_ASSERT_FLOAT_WITHIN(1e-6, 0.2f, s.r);
  s = toWheels(0, 1.0f, TRACK_WIDTH_M);  // CCW spin: left back, right forward
  TEST_ASSERT_FLOAT_WITHIN(1e-6, -0.086f, s.l);
  TEST_ASSERT_FLOAT_WITHIN(1e-6, 0.086f, s.r);
}

void test_to_chassis_is_inverse() {
  float v, w;
  toChassis(toWheels(0.13f, -0.7f, TRACK_WIDTH_M), TRACK_WIDTH_M, v, w);
  TEST_ASSERT_FLOAT_WITHIN(1e-5, 0.13f, v);
  TEST_ASSERT_FLOAT_WITHIN(1e-5, -0.7f, w);
}

void test_unit_conversion() {
  // 0.25 m/s on a 100 mm wheel = 0.7958 rev/s = 3259.5 steps/s
  TEST_ASSERT_FLOAT_WITHIN(0.5f, 3259.5f, mpsToSteps(0.25f, WHEEL_DIAMETER_M, STS_STEPS_PER_REV));
  TEST_ASSERT_FLOAT_WITHIN(1e-5, PI_F * 0.1f, stepsToMeters(4096, WHEEL_DIAMETER_M, 4096));
  TEST_ASSERT_EQUAL_INT16(3400, clampSteps(9999.0f, 3400));
  TEST_ASSERT_EQUAL_INT16(-3400, clampSteps(-9999.0f, 3400));
  TEST_ASSERT_EQUAL_INT16(12, clampSteps(11.6f, 3400));
  TEST_ASSERT_EQUAL_INT16(0, clampSteps(NAN, 3400));
}

void test_wrap_delta() {
  TEST_ASSERT_EQUAL_INT32(11, wrapDelta(5, 4090, 4096));
  TEST_ASSERT_EQUAL_INT32(-11, wrapDelta(4090, 5, 4096));
  TEST_ASSERT_EQUAL_INT32(100, wrapDelta(1100, 1000, 4096));
  TEST_ASSERT_EQUAL_INT32(-100, wrapDelta(1000, 1100, 4096));
  TEST_ASSERT_EQUAL_INT32(0, wrapDelta(4095, 4095, 4096));
  TEST_ASSERT_EQUAL_INT32(2047, wrapDelta(2047, 0, 4096));
  TEST_ASSERT_EQUAL_INT32(-2048, wrapDelta(2048, 0, 4096));
}

void test_unwrapper_accumulates_across_wrap() {
  WheelUnwrapper u;
  int32_t d = 0, total = 0;
  TEST_ASSERT_FALSE(u.update(4000, 0, 500, 4096, d));  // seeds
  int raw = 4000;
  for (int i = 1; i <= 100; i++) {  // +60 steps per sample, wraps twice
    raw = (raw + 60) % 4096;
    TEST_ASSERT_TRUE(u.update(raw, i * 20, 500, 4096, d));
    total += d;
  }
  TEST_ASSERT_EQUAL_INT32(6000, total);
  for (int i = 101; i <= 200; i++) {  // and back again
    raw = (raw - 60 + 4096) % 4096;
    u.update(raw, i * 20, 500, 4096, d);
    total += d;
  }
  TEST_ASSERT_EQUAL_INT32(0, total);
}

void test_unwrapper_reseeds_after_gap_and_normalises() {
  WheelUnwrapper u;
  int32_t d = 0;
  u.update(100, 0, 500, 4096, d);
  TEST_ASSERT_TRUE(u.update(150, 20, 500, 4096, d));
  TEST_ASSERT_EQUAL_INT32(50, d);
  // servo silent for 1 s: the next sample only re-seeds
  TEST_ASSERT_FALSE(u.update(3000, 1020, 500, 4096, d));
  TEST_ASSERT_TRUE(u.update(3010, 1040, 500, 4096, d));
  TEST_ASSERT_EQUAL_INT32(10, d);
  // negative (sign-magnitude) and multi-turn values are folded into 0..4095
  TEST_ASSERT_TRUE(u.update(-1086, 1060, 500, 4096, d));  // == 3010 mod 4096
  TEST_ASSERT_EQUAL_INT32(0, d);
  TEST_ASSERT_TRUE(u.update(4096 + 3020, 1080, 500, 4096, d));
  TEST_ASSERT_EQUAL_INT32(10, d);
}

void test_odometry_straight() {
  Odometry o(TRACK_WIDTH_M);
  for (int i = 0; i < 50; i++) o.update(0.02f, 0.02f, 0.02f);
  TEST_ASSERT_FLOAT_WITHIN(1e-4, 1.0f, o.x);
  TEST_ASSERT_FLOAT_WITHIN(1e-4, 0.0f, o.y);
  TEST_ASSERT_FLOAT_WITHIN(1e-5, 0.0f, o.th);
  TEST_ASSERT_FLOAT_WITHIN(1e-4, 1.0f, o.v);
}

void test_odometry_spin_in_place() {
  Odometry o(TRACK_WIDTH_M);
  const float arc = (PI_F / 2) * TRACK_WIDTH_M / 2;  // each wheel's travel for 90 deg
  for (int i = 0; i < 10; i++) o.update(-arc / 10, arc / 10, 0.02f);
  TEST_ASSERT_FLOAT_WITHIN(1e-4, PI_F / 2, o.th);
  TEST_ASSERT_FLOAT_WITHIN(1e-5, 0.0f, o.x);
  TEST_ASSERT_FLOAT_WITHIN(1e-5, 0.0f, o.y);
  TEST_ASSERT_TRUE(o.w > 0);
}

void test_odometry_quarter_circle() {
  // radius 0.5 m left turn, 90 degrees: ends at (0.5, 0.5), heading pi/2
  Odometry o(TRACK_WIDTH_M);
  const float R = 0.5f, ang = PI_F / 2;
  const int N = 200;
  const float dl = (R - TRACK_WIDTH_M / 2) * ang / N, dr = (R + TRACK_WIDTH_M / 2) * ang / N;
  for (int i = 0; i < N; i++) o.update(dl, dr, 0.02f);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, 0.5f, o.x);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, 0.5f, o.y);
  TEST_ASSERT_FLOAT_WITHIN(1e-4, PI_F / 2, o.th);
}

void test_heading_wraps() {
  Odometry o(TRACK_WIDTH_M);
  const float arc = PI_F * TRACK_WIDTH_M / 2;  // 180 deg
  for (int i = 0; i < 30; i++) o.update(-arc / 10, arc / 10, 0.02f);  // 540 deg
  TEST_ASSERT_TRUE(o.th <= PI_F && o.th > -PI_F);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, PI_F, fabsf(o.th));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_config_constants);
  RUN_TEST(test_to_wheels_straight_and_spin);
  RUN_TEST(test_to_chassis_is_inverse);
  RUN_TEST(test_unit_conversion);
  RUN_TEST(test_wrap_delta);
  RUN_TEST(test_unwrapper_accumulates_across_wrap);
  RUN_TEST(test_unwrapper_reseeds_after_gap_and_normalises);
  RUN_TEST(test_odometry_straight);
  RUN_TEST(test_odometry_spin_in_place);
  RUN_TEST(test_odometry_quarter_circle);
  RUN_TEST(test_heading_wraps);
  return UNITY_END();
}
