#include <stdlib.h>
#include <unity.h>

#include "config.h"
#include "visor.h"

using namespace face;

void setUp() {}
void tearDown() {}

static Visor make() { return Visor(VISOR_OPEN_TIMEOUT_MS, VISOR_CLOSE_MS); }

// run the machine with a fixed switch level for ms milliseconds
static void run(Visor& v, bool up, uint32_t& t, uint32_t ms) {
  for (uint32_t i = 0; i < ms; i++, t++) v.update(up, t);
}

void test_boot_closes() {
  Visor v = make();
  uint32_t t = 0;
  v.boot(t);
  TEST_ASSERT_FALSE(v.servoOpen());
  TEST_ASSERT_EQUAL(V_MOVING, v.report());
  TEST_ASSERT_TRUE(v.takeChanged());
  run(v, false, t, VISOR_CLOSE_MS + 5);
  TEST_ASSERT_EQUAL(V_CLOSED, v.report());
  TEST_ASSERT_TRUE(v.takeChanged());
  TEST_ASSERT_EQUAL_STRING("closed", visorName(v.report()));
}

void test_open_reported_only_when_switch_closes() {
  Visor v = make();
  uint32_t t = 0;
  v.boot(t);
  run(v, false, t, 1000);
  v.command(true, t);
  TEST_ASSERT_TRUE(v.servoOpen());
  TEST_ASSERT_EQUAL(V_MOVING, v.report());
  run(v, false, t, 400);  // still travelling
  TEST_ASSERT_EQUAL(V_MOVING, v.report());
  run(v, true, t, 1);  // switch closes
  TEST_ASSERT_EQUAL(V_OPEN, v.report());
  TEST_ASSERT_EQUAL_STRING("open", visorName(v.report()));
}

void test_open_timeout_jams_and_closes_again() {
  Visor v = make();
  uint32_t t = 0;
  v.boot(t);
  run(v, false, t, 1000);
  v.takeChanged();
  v.command(true, t);
  run(v, false, t, VISOR_OPEN_TIMEOUT_MS - 1);
  TEST_ASSERT_EQUAL(V_MOVING, v.report());
  run(v, false, t, 2);
  TEST_ASSERT_EQUAL(V_JAMMED, v.report());
  TEST_ASSERT_FALSE(v.servoOpen());  // driving closed again
  run(v, false, t, VISOR_CLOSE_MS + 5);
  TEST_ASSERT_EQUAL(V_CLOSED, v.report());
}

void test_knocked_down_while_open() {
  Visor v = make();
  uint32_t t = 0;
  v.boot(t);
  run(v, false, t, 1000);
  v.command(true, t);
  run(v, true, t, 100);
  TEST_ASSERT_EQUAL(V_OPEN, v.report());
  run(v, false, t, 1);
  TEST_ASSERT_EQUAL(V_JAMMED, v.report());
  TEST_ASSERT_FALSE(v.servoOpen());
}

void test_close_from_open() {
  Visor v = make();
  uint32_t t = 0;
  v.boot(t);
  run(v, false, t, 1000);
  v.command(true, t);
  run(v, true, t, 100);
  v.command(false, t);
  TEST_ASSERT_EQUAL(V_MOVING, v.report());  // camera unavailable at once
  run(v, true, t, 50);                       // switch still pressed briefly
  TEST_ASSERT_EQUAL(V_MOVING, v.report());
  run(v, false, t, VISOR_CLOSE_MS);
  TEST_ASSERT_EQUAL(V_CLOSED, v.report());
}

void test_stuck_up_after_close() {
  Visor v = make();
  uint32_t t = 0;
  v.boot(t);
  run(v, true, t, VISOR_CLOSE_MS + 5);  // switch never releases
  TEST_ASSERT_EQUAL(V_JAMMED, v.report());
  TEST_ASSERT_FALSE(v.servoOpen());
  run(v, false, t, 1);  // finally drops
  TEST_ASSERT_EQUAL(V_CLOSED, v.report());
}

void test_lifted_by_hand_is_never_open() {
  Visor v = make();
  uint32_t t = 0;
  v.boot(t);
  run(v, false, t, 1000);
  run(v, true, t, 500);  // someone lifts the visor; we never asked
  TEST_ASSERT_EQUAL(V_JAMMED, v.report());
  TEST_ASSERT_FALSE(v.servoOpen());
}

void test_property_open_implies_switch_up() {
  // random commands and switch levels: `open` is never reported while the
  // switch reads not-up
  srand(7);
  Visor v = make();
  uint32_t t = 0;
  v.boot(t);
  bool up = false;
  for (int i = 0; i < 200000; i++, t++) {
    if (rand() % 500 == 0) v.command(rand() % 2, t);
    if (rand() % 300 == 0) up = !up;
    v.update(up, t);
    if (v.report() == V_OPEN) TEST_ASSERT_TRUE(up);
  }
}

void test_repeat_commands_are_harmless() {
  Visor v = make();
  uint32_t t = 0;
  v.boot(t);
  run(v, false, t, 1000);
  v.takeChanged();
  v.command(false, t);  // already closed
  TEST_ASSERT_FALSE(v.takeChanged());
  v.command(true, t);
  run(v, true, t, 10);
  v.takeChanged();
  v.command(true, t);  // already open
  TEST_ASSERT_FALSE(v.takeChanged());
  TEST_ASSERT_EQUAL(V_OPEN, v.report());
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_boot_closes);
  RUN_TEST(test_open_reported_only_when_switch_closes);
  RUN_TEST(test_open_timeout_jams_and_closes_again);
  RUN_TEST(test_knocked_down_while_open);
  RUN_TEST(test_close_from_open);
  RUN_TEST(test_stuck_up_after_close);
  RUN_TEST(test_lifted_by_hand_is_never_open);
  RUN_TEST(test_property_open_implies_switch_up);
  RUN_TEST(test_repeat_commands_are_harmless);
  return UNITY_END();
}
