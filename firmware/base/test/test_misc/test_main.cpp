// Debouncer, head conversions, IMU filter, LED animations.
#include <math.h>
#include <unity.h>

#include "config.h"
#include "debounce.h"
#include "head.h"
#include "imu_filter.h"
#include "led_anim.h"

void setUp() {}
void tearDown() {}

void test_debounce_fast_press_slow_release() {
  Debouncer d(BUMP_PRESS_MS, BUMP_RELEASE_MS);
  TEST_ASSERT_FALSE(d.update(true, 0));
  TEST_ASSERT_FALSE(d.update(true, 2));
  TEST_ASSERT_TRUE(d.update(true, 3));     // pressed after 3 ms
  TEST_ASSERT_TRUE(d.update(false, 4));    // bounce
  TEST_ASSERT_TRUE(d.update(true, 5));
  TEST_ASSERT_TRUE(d.update(false, 10));
  TEST_ASSERT_TRUE(d.update(false, 29));
  TEST_ASSERT_FALSE(d.update(false, 30));  // released after 20 ms stable
}

void test_debounce_rejects_glitch() {
  Debouncer d(BUMP_PRESS_MS, BUMP_RELEASE_MS);
  d.update(true, 0);
  d.update(false, 1);  // 1 ms glitch
  TEST_ASSERT_FALSE(d.update(false, 10));
}

void test_head_limits_and_conversion() {
  head::Axis pan = head::panAxis(), tilt = head::tiltAxis();
  TEST_ASSERT_EQUAL_FLOAT(-150, pan.min_deg);
  TEST_ASSERT_EQUAL_FLOAT(150, pan.max_deg);
  TEST_ASSERT_EQUAL_FLOAT(-15, tilt.min_deg);  // PROTOCOL: -15..30 (stops at -16 / +31)
  TEST_ASSERT_EQUAL_FLOAT(30, tilt.max_deg);
  TEST_ASSERT_EQUAL(2048, head::degToSteps(pan, 0));
  TEST_ASSERT_EQUAL(2048 + 1024, head::degToSteps(pan, 90));
  TEST_ASSERT_EQUAL(head::degToSteps(pan, 150), head::degToSteps(pan, 400));    // clamped
  TEST_ASSERT_EQUAL(head::degToSteps(tilt, -15), head::degToSteps(tilt, -90));  // clamped
  TEST_ASSERT_EQUAL(head::degToSteps(tilt, 30), head::degToSteps(tilt, 45));
  TEST_ASSERT_FLOAT_WITHIN(0.1f, 30.0f, head::stepsToDeg(tilt, head::degToSteps(tilt, 45)));
  TEST_ASSERT_EQUAL(2048, head::degToSteps(pan, NAN));
}

void test_head_speed_never_zero_and_capped() {
  // 120 deg/s = 1365 steps/s; 0 or missing -> default, never 0 (= "max" to the servo)
  TEST_ASSERT_EQUAL(1365, head::speedToSteps(500, HEAD_SPEED_MAX_DPS, HEAD_SPEED_DEFAULT_DPS));
  TEST_ASSERT_EQUAL(683, head::speedToSteps(0, HEAD_SPEED_MAX_DPS, HEAD_SPEED_DEFAULT_DPS));
  TEST_ASSERT_EQUAL(683, head::speedToSteps(-5, HEAD_SPEED_MAX_DPS, HEAD_SPEED_DEFAULT_DPS));
  TEST_ASSERT_EQUAL(1, head::speedToSteps(0.01f, HEAD_SPEED_MAX_DPS, HEAD_SPEED_DEFAULT_DPS));
}

void test_imu_level_and_tilted() {
  imu::Complementary f(IMU_COMP_ALPHA);
  const float level[3] = {0, 0, 1}, still[3] = {0, 0, 0};
  f.update(level, still, 0.01f);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, 0, f.roll);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, 0, f.pitch);
  // nose UP 30 deg (REP-103: +pitch = nose down): "up" has a +x component
  const float nose_down[3] = {sinf(30 * 0.0174533f), 0, cosf(30 * 0.0174533f)};
  for (int i = 0; i < 500; i++) f.update(nose_down, still, 0.01f);
  TEST_ASSERT_FLOAT_WITHIN(0.5f, -30.0f, f.pitch);
  // rolled 40 deg
  imu::Complementary g(IMU_COMP_ALPHA);
  const float rolled[3] = {0, sinf(40 * 0.0174533f), cosf(40 * 0.0174533f)};
  g.update(rolled, still, 0.01f);
  TEST_ASSERT_FLOAT_WITHIN(0.1f, 40.0f, g.roll);
}

void test_imu_gyro_integrates_and_accel_ignored_when_not_1g() {
  imu::Complementary f(IMU_COMP_ALPHA);
  const float level[3] = {0, 0, 1}, spin[3] = {0, 0, 90};  // 90 deg/s yaw
  for (int i = 0; i < 100; i++) f.update(level, spin, 0.01f);
  TEST_ASSERT_FLOAT_WITHIN(0.1f, 90.0f, f.yaw);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, 90.0f, f.gz);
  for (int i = 0; i < 100; i++) f.update(level, spin, 0.01f);
  TEST_ASSERT_FLOAT_WITHIN(0.2f, 180.0f, fabsf(f.yaw));  // wraps
  // a 3 g knock sideways must not yank roll
  const float knock[3] = {0, 3, 1};
  const float still[3] = {0, 0, 0};
  f.update(knock, still, 0.01f);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 0, f.roll);
}

void test_imu_rotation() {
  const int R[3][3] = {{0, 1, 0}, {-1, 0, 0}, {0, 0, 1}};  // board turned 90 deg
  const float in[3] = {1, 2, 3};
  float out[3];
  imu::rotate(R, in, out);
  TEST_ASSERT_EQUAL_FLOAT(2, out[0]);
  TEST_ASSERT_EQUAL_FLOAT(-1, out[1]);
  TEST_ASSERT_EQUAL_FLOAT(3, out[2]);
}

static void quatAxisAngle(float ax, float ay, float az, float deg, float q[4]) {
  const float h = deg * 0.0174533f / 2;
  q[0] = cosf(h);
  q[1] = ax * sinf(h);
  q[2] = ay * sinf(h);
  q[3] = az * sinf(h);
}

void test_quat_orientation() {
  const int I[3][3] = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}};
  float q[4], r, p, y;
  quatAxisAngle(0, 0, 1, 0, q);
  imu::orientationFromQuat(q, I, r, p, y);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, 0, r);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, 0, p);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, 0, y);
  quatAxisAngle(1, 0, 0, 30, q);  // rolled 30 deg about x
  imu::orientationFromQuat(q, I, r, p, y);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 30, r);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 0, p);
  quatAxisAngle(0, 1, 0, 20, q);  // pitched 20 deg about y (nose down)
  imu::orientationFromQuat(q, I, r, p, y);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 20, p);
  quatAxisAngle(0, 0, 1, 90, q);  // yawed 90 left
  imu::orientationFromQuat(q, I, r, p, y);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 90, y);
  // board mounted turned 90 deg about z (sensor x = robot left): robot rolls 30
  // deg about its own x, which is the sensor's -y axis... use the matrix to check
  const int R[3][3] = {{0, -1, 0}, {1, 0, 0}, {0, 0, 1}};  // robot = R * sensor
  // robot x axis in sensor coords = R^T * (1,0,0) = (0,-1,0)
  quatAxisAngle(0, -1, 0, 30, q);
  imu::orientationFromQuat(q, R, r, p, y);
  TEST_ASSERT_FLOAT_WITHIN(0.05f, 30, r);
  TEST_ASSERT_FLOAT_WITHIN(0.05f, 0, p);
}

void test_led_modes() {
  led::Rgb px[LED_COUNT];
  const led::Rgb orange = led::defaultColour(led::IDLE);
  TEST_ASSERT_EQUAL_UINT8(0xD9, orange.r);
  led::render(led::OFF, orange, 1234, 50, 255, px, LED_COUNT);
  for (auto& p : px) TEST_ASSERT_TRUE(p.r == 0 && p.g == 0 && p.b == 0);
  // global brightness cap is respected in every mode at many instants
  for (int m = 0; m < led::MODE_COUNT; m++)
    for (uint32_t t = 0; t < 10000; t += 37) {
      led::render((led::Mode)m, {255, 255, 255}, t, 60, LED_MAX_BRIGHTNESS, px, LED_COUNT);
      for (auto& p : px) TEST_ASSERT_TRUE(p.r <= LED_MAX_BRIGHTNESS && p.g <= LED_MAX_BRIGHTNESS);
    }
  // alert blinks
  led::render(led::ALERT, {255, 0, 0}, 100, 0, 255, px, LED_COUNT);
  TEST_ASSERT_EQUAL_UINT8(255, px[0].r);
  led::render(led::ALERT, {255, 0, 0}, 300, 0, 255, px, LED_COUNT);
  TEST_ASSERT_EQUAL_UINT8(0, px[0].r);
  // charge: 50 % lights the first half of the ring
  TEST_ASSERT_EQUAL(16, LED_COUNT);
  led::render(led::CHARGE, {0, 200, 0}, 0, 50, 255, px, LED_COUNT);
  const int half = LED_COUNT / 2;
  TEST_ASSERT_TRUE(px[half - 1].g > px[half + 1].g);
  TEST_ASSERT_TRUE(px[0].g == px[half - 1].g);
  TEST_ASSERT_TRUE(px[LED_COUNT - 1].g < px[0].g);
  led::Mode mm;
  TEST_ASSERT_TRUE(led::modeFromName("charge", mm));
  TEST_ASSERT_EQUAL(led::CHARGE, mm);
  TEST_ASSERT_FALSE(led::modeFromName("rainbow", mm));
  TEST_ASSERT_FALSE(led::modeFromName(nullptr, mm));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_debounce_fast_press_slow_release);
  RUN_TEST(test_debounce_rejects_glitch);
  RUN_TEST(test_head_limits_and_conversion);
  RUN_TEST(test_head_speed_never_zero_and_capped);
  RUN_TEST(test_imu_level_and_tilted);
  RUN_TEST(test_imu_gyro_integrates_and_accel_ignored_when_not_1g);
  RUN_TEST(test_imu_rotation);
  RUN_TEST(test_quat_orientation);
  RUN_TEST(test_led_modes);
  return UNITY_END();
}
