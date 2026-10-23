#include <unity.h>

#include "config.h"
#include "gesture.h"

using namespace face;

void setUp() {}
void tearDown() {}

// Feed a touch timeline: hold `level` from t0 to t1 (1 ms steps), collecting gestures.
struct Run {
  GestureDetector d{TOUCH_DEBOUNCE_MS, TOUCH_HOLD_MS, TOUCH_DOUBLE_GAP_MS};
  Gesture got[8];
  uint32_t when[8];
  int n = 0;
  uint32_t t = 0;
  void hold(bool level, uint32_t ms) {
    for (uint32_t i = 0; i < ms; i++, t++) {
      Gesture g = d.update(level, t);
      while (g != G_NONE) {
        if (n < 8) got[n] = g, when[n] = t, n++;
        g = d.pending() ? d.update(level, t) : G_NONE;
      }
    }
  }
};

void test_pat() {
  Run r;
  r.hold(false, 100);
  r.hold(true, 200);
  TEST_ASSERT_EQUAL(0, r.n);  // not yet: could become a double
  r.hold(false, 500);
  TEST_ASSERT_EQUAL(1, r.n);
  TEST_ASSERT_EQUAL(G_PAT, r.got[0]);
  TEST_ASSERT_EQUAL_STRING("pat", gestureName(r.got[0]));
}

void test_hold_fires_at_threshold_once() {
  Run r;
  r.hold(false, 100);
  r.hold(true, 3000);
  TEST_ASSERT_EQUAL(1, r.n);
  TEST_ASSERT_EQUAL(G_HOLD, r.got[0]);
  // fires 1.5 s after the debounced press, not on release
  TEST_ASSERT_UINT32_WITHIN(5, 100 + TOUCH_DEBOUNCE_MS + TOUCH_HOLD_MS, r.when[0]);
  r.hold(false, 1000);
  TEST_ASSERT_EQUAL(1, r.n);  // no pat after a hold
}

void test_short_of_hold_is_a_pat() {
  Run r;
  r.hold(true, 1400);
  r.hold(false, 600);
  TEST_ASSERT_EQUAL(1, r.n);
  TEST_ASSERT_EQUAL(G_PAT, r.got[0]);
}

void test_double() {
  Run r;
  r.hold(false, 50);
  r.hold(true, 120);
  r.hold(false, 150);
  r.hold(true, 120);
  r.hold(false, 600);
  TEST_ASSERT_EQUAL(1, r.n);
  TEST_ASSERT_EQUAL(G_DOUBLE, r.got[0]);
}

void test_two_slow_taps_are_two_pats() {
  Run r;
  r.hold(true, 120);
  r.hold(false, 800);
  r.hold(true, 120);
  r.hold(false, 800);
  TEST_ASSERT_EQUAL(2, r.n);
  TEST_ASSERT_EQUAL(G_PAT, r.got[0]);
  TEST_ASSERT_EQUAL(G_PAT, r.got[1]);
}

void test_tap_then_hold_reports_pat_and_hold() {
  Run r;
  r.hold(true, 120);
  r.hold(false, 150);
  r.hold(true, 2000);
  TEST_ASSERT_EQUAL(2, r.n);
  TEST_ASSERT_EQUAL(G_PAT, r.got[0]);
  TEST_ASSERT_EQUAL(G_HOLD, r.got[1]);
}

void test_glitches_ignored() {
  Run r;
  for (int i = 0; i < 20; i++) {  // 5 ms spikes, shorter than the debounce
    r.hold(true, 5);
    r.hold(false, 50);
  }
  r.hold(false, 1000);
  TEST_ASSERT_EQUAL(0, r.n);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_pat);
  RUN_TEST(test_hold_fires_at_threshold_once);
  RUN_TEST(test_short_of_hold_is_a_pat);
  RUN_TEST(test_double);
  RUN_TEST(test_two_slow_taps_are_two_pats);
  RUN_TEST(test_tap_then_hold_reports_pat_and_hold);
  RUN_TEST(test_glitches_ignored);
  return UNITY_END();
}
