// The EEPROM plan written to every STS3215 at bring-up.
#include <string.h>
#include <unity.h>

#include "config.h"
#include "head.h"
#include "servo_cfg.h"

using namespace servo;

void setUp() {}
void tearDown() {}

static const RegSetting* find(const RegSetting* p, int n, uint8_t reg) {
  for (int i = 0; i < n; i++)
    if (p[i].reg == reg) return &p[i];
  return nullptr;
}

void test_torque_ceilings() {
  // wheels <= 30 %, pan/tilt <= 10 % (reg 16 / 48 units: 0.1 %)
  TEST_ASSERT_TRUE(torqueLimit(WHEEL) <= 300);
  TEST_ASSERT_TRUE(torqueLimit(PAN) <= 100);
  TEST_ASSERT_TRUE(torqueLimit(TILT) <= 100);
  TEST_ASSERT_TRUE(torqueLimit(WHEEL) >= 50);  // still enough to drive (~3 % needed)
  RegSetting p[8];
  for (int k = WHEEL; k <= TILT; k++) {
    const int n = eepromPlan((Kind)k, p);
    const RegSetting* t = find(p, n, 16);
    TEST_ASSERT_NOT_NULL(t);
    TEST_ASSERT_EQUAL(2, t->size);
    TEST_ASSERT_EQUAL_UINT16(torqueLimit((Kind)k), t->value);
  }
}

void test_protection_registers_per_regs_csv() {
  // addresses and sizes from "ST3215 Memory Table Parsing V3.7"
  RegSetting p[8];
  for (int k = WHEEL; k <= TILT; k++) {
    const int n = eepromPlan((Kind)k, p);
    const RegSetting* cur = find(p, n, 28);  // protection current, 2 bytes, 6.5 mA
    const RegSetting* ptq = find(p, n, 34);  // protection torque, 1 byte, %
    const RegSetting* ptm = find(p, n, 35);  // protection time, 1 byte, 10 ms
    const RegSetting* otq = find(p, n, 36);  // overload torque, 1 byte, %
    const RegSetting* oct = find(p, n, 38);  // overcurrent protection time, 1 byte, 10 ms
    TEST_ASSERT_NOT_NULL(cur);
    TEST_ASSERT_NOT_NULL(ptq);
    TEST_ASSERT_NOT_NULL(ptm);
    TEST_ASSERT_NOT_NULL(otq);
    TEST_ASSERT_NOT_NULL(oct);
    TEST_ASSERT_EQUAL(2, cur->size);
    TEST_ASSERT_EQUAL(1, ptq->size);
    TEST_ASSERT_TRUE(cur->value <= 511);                 // table max
    TEST_ASSERT_TRUE(ptq->value <= 100 && otq->value <= 100);
    TEST_ASSERT_TRUE(ptm->value <= 254 && oct->value <= 254);
    // the overload threshold sits below the torque limit, so it can trip
    TEST_ASSERT_TRUE(otq->value * 10 <= torqueLimit((Kind)k));
    TEST_ASSERT_TRUE(ptq->value <= otq->value);
    for (int i = 0; i < n; i++) TEST_ASSERT_TRUE(p[i].reg != 33 && p[i].reg != 5);  // never mode/ID
  }
  // the head is gentler than the wheels in every respect
  RegSetting w[8], h[8];
  const int nw = eepromPlan(WHEEL, w), nh = eepromPlan(TILT, h);
  TEST_ASSERT_TRUE(find(h, nh, 28)->value < find(w, nw, 28)->value);
  TEST_ASSERT_TRUE(find(h, nh, 35)->value <= find(w, nw, 35)->value);
}

void test_tilt_angle_limits_inside_stops() {
  TEST_ASSERT_EQUAL_FLOAT(-15.0f, TILT_MIN_DEG);
  TEST_ASSERT_EQUAL_FLOAT(30.0f, TILT_MAX_DEG);
  RegSetting p[8];
  const int n = eepromPlan(TILT, p);
  const RegSetting* lo = find(p, n, 9);
  const RegSetting* hi = find(p, n, 11);
  TEST_ASSERT_NOT_NULL(lo);
  TEST_ASSERT_NOT_NULL(hi);
  TEST_ASSERT_TRUE(lo->value < hi->value);
  const head::Axis a = head::tiltAxis();
  float d1 = head::stepsToDeg(a, lo->value), d2 = head::stepsToDeg(a, hi->value);
  const float dmin = d1 < d2 ? d1 : d2, dmax = d1 < d2 ? d2 : d1;
  // 1..2 deg inside the -16 / +31 mechanical stops
  TEST_ASSERT_TRUE(dmin > -16.0f && dmin <= -14.0f);
  TEST_ASSERT_TRUE(dmax < 31.0f && dmax >= 29.0f);
  // and the firmware clamp never asks beyond them
  TEST_ASSERT_EQUAL_FLOAT(30.0f, head::clampDeg(a, 45));
  TEST_ASSERT_EQUAL_FLOAT(-15.0f, head::clampDeg(a, -20));
}

void test_pan_angle_limits_and_wheels_have_none() {
  RegSetting p[8];
  int n = eepromPlan(PAN, p);
  const RegSetting* lo = find(p, n, 9);
  const RegSetting* hi = find(p, n, 11);
  TEST_ASSERT_NOT_NULL(lo);
  TEST_ASSERT_EQUAL_UINT16(head::degToSteps(head::panAxis(), PAN_DIR > 0 ? -150 : 150), lo->value);
  TEST_ASSERT_TRUE(hi->value <= 4095);
  n = eepromPlan(WHEEL, p);
  TEST_ASSERT_NULL(find(p, n, 9));  // wheel mode: no angle limits written
  TEST_ASSERT_NULL(find(p, n, 11));
}

void test_unloading_conditions() {
  TEST_ASSERT_EQUAL(-1, unloadingFix(44));        // factory 44 = b2 b3 b5: fine
  TEST_ASSERT_EQUAL(0x2C | 0x01, unloadingFix(0x05));  // b3/b5 missing -> added
  TEST_ASSERT_EQUAL(-1, unloadingFix(-1));        // unreadable: caller decides
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_torque_ceilings);
  RUN_TEST(test_protection_registers_per_regs_csv);
  RUN_TEST(test_tilt_angle_limits_inside_stops);
  RUN_TEST(test_pan_angle_limits_and_wheels_have_none);
  RUN_TEST(test_unloading_conditions);
  return UNITY_END();
}
