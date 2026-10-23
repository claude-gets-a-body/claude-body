#include <math.h>
#include <unity.h>

#include "config.h"
#include "power.h"

using namespace power;

void setUp() {}
void tearDown() {}

// pin millivolts that correspond to a given pack / contact voltage
static float batPin(float v) { return v * 1000.0f / BAT_DIVIDER_RATIO; }
static float chgPin(float v) { return v * 1000.0f / CHG_DIVIDER_RATIO; }
static float ntcPin(float r) { return ADC_VREF_MV * r / (r + NTC_R_FIXED); }

void test_battery_curve_end_points_and_shape() {
  TEST_ASSERT_EQUAL(100, batteryPct(12.6f));
  TEST_ASSERT_EQUAL(100, batteryPct(13.0f));
  TEST_ASSERT_EQUAL(0, batteryPct(9.0f));
  TEST_ASSERT_EQUAL(0, batteryPct(7.0f));
  TEST_ASSERT_EQUAL(40, batteryPct(11.1f));  // 3.70 V/cell
  TEST_ASSERT_EQUAL(0, batteryPct(NAN));
  int prev = -1;
  for (float v = 8.5f; v <= 12.8f; v += 0.05f) {  // monotonic
    const int p = batteryPct(v);
    TEST_ASSERT_TRUE(p >= prev);
    prev = p;
  }
}

void test_ntc_conversion() {
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 25.0f, ntcCelsius(10000.0f, NTC_R25, NTC_BETA));
  TEST_ASSERT_FLOAT_WITHIN(0.2f, 50.0f, ntcCelsius(3588.0f, NTC_R25, NTC_BETA));
  TEST_ASSERT_FLOAT_WITHIN(0.3f, 0.0f, ntcCelsius(33620.0f, NTC_R25, NTC_BETA));
  TEST_ASSERT_TRUE(isnan(ntcCelsius(-1, NTC_R25, NTC_BETA)));
  TEST_ASSERT_FLOAT_WITHIN(1.0f, 10000.0f, ntcResistance(1650.0f, 3300.0f, 10000.0f));
  TEST_ASSERT_TRUE(ntcResistance(5.0f, 3300.0f, 10000.0f) < 0);     // shorted
  TEST_ASSERT_TRUE(ntcResistance(3295.0f, 3300.0f, 10000.0f) < 0);  // open
}

void test_monitor_reads_and_seeds() {
  Monitor m(defaultConfig());
  EventQueue ev;
  m.update(0, batPin(11.1f), ntcPin(10000), chgPin(0), ev);
  TEST_ASSERT_TRUE(m.seeded());
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 11.1f, m.batV());  // first sample taken as-is
  TEST_ASSERT_EQUAL(40, m.pct());
  TEST_ASSERT_TRUE(m.ntcOk());
  TEST_ASSERT_FLOAT_WITHIN(0.2f, 25.0f, m.packC());
  TEST_ASSERT_FALSE(m.onDock());
  TEST_ASSERT_EQUAL(0, ev.size());
}

void test_monitor_filters_but_follows_bms_cutoff() {
  Monitor m(defaultConfig());
  EventQueue ev;
  m.update(0, batPin(12.0f), ntcPin(10000), 0, ev);
  m.update(200, batPin(11.0f), ntcPin(10000), 0, ev);  // load sag: filtered
  TEST_ASSERT_TRUE(m.batV() > 11.9f);
  m.update(400, batPin(0.5f), ntcPin(10000), 0, ev);  // BMS cut: immediate
  TEST_ASSERT_TRUE(m.batV() < 1.0f);
}

void test_monitor_dock_debounce_and_charging() {
  Monitor m(defaultConfig());
  EventQueue ev;
  uint32_t t = 0;
  m.update(t, batPin(11.5f), ntcPin(10000), chgPin(0), ev);
  // contacts touch the dock: 12.3 V on the contacts, pack at 11.5 V
  for (int i = 0; i < 3; i++) m.update(t += 200, batPin(11.5f), ntcPin(10000), chgPin(12.3f), ev);
  TEST_ASSERT_FALSE(m.onDock());  // stable for 400 ms < 500 ms debounce
  m.update(t += 200, batPin(11.5f), ntcPin(10000), chgPin(12.3f), ev);
  TEST_ASSERT_TRUE(m.onDock());
  TEST_ASSERT_TRUE(m.charging());
  TEST_ASSERT_TRUE(ev.contains("dock_on"));
  // full: contacts no higher than the pack -> on dock, not charging
  m.update(t += 200, batPin(12.5f), ntcPin(10000), chgPin(12.5f), ev);
  TEST_ASSERT_TRUE(m.onDock());
  TEST_ASSERT_FALSE(m.charging());
  ev.clear();
  for (int i = 0; i < 4; i++) m.update(t += 200, batPin(12.5f), ntcPin(10000), chgPin(0.1f), ev);
  TEST_ASSERT_FALSE(m.onDock());
  TEST_ASSERT_TRUE(ev.contains("dock_off"));
}

void test_monitor_low_battery_event_once() {
  Monitor m(defaultConfig());
  EventQueue ev;
  uint32_t t = 0;
  m.update(t, batPin(10.0f), ntcPin(10000), 0, ev);  // ~5 %
  TEST_ASSERT_TRUE(ev.contains("low_battery"));
  ev.clear();
  for (int i = 0; i < 10; i++) m.update(t += 200, batPin(10.0f), ntcPin(10000), 0, ev);
  TEST_ASSERT_EQUAL(0, ev.size());
}

void test_monitor_ntc_fault() {
  Monitor m(defaultConfig());
  EventQueue ev;
  m.update(0, batPin(11.5f), ADC_VREF_MV, 0, ev);  // open NTC reads the rail
  TEST_ASSERT_FALSE(m.ntcOk());
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_battery_curve_end_points_and_shape);
  RUN_TEST(test_ntc_conversion);
  RUN_TEST(test_monitor_reads_and_seeds);
  RUN_TEST(test_monitor_filters_but_follows_bms_cutoff);
  RUN_TEST(test_monitor_dock_debounce_and_charging);
  RUN_TEST(test_monitor_low_battery_event_once);
  RUN_TEST(test_monitor_ntc_fault);
  return UNITY_END();
}
