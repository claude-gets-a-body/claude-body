#include <string.h>
#include <unity.h>

#include "config.h"
#include "floor.h"
#include "reflex.h"

using namespace reflex;

void setUp() {}
void tearDown() {}

// A healthy, upright, idle robot with a live `vel` stream.
static Inputs calm(uint32_t now) {
  Inputs in;
  in.now_ms = now;
  for (int i = 0; i < 3; i++) in.drop[i] = false;
  in.fwd_mm[0] = in.fwd_mm[1] = tof::kNoTarget;
  in.imu_ok = true;
  in.ntc_ok = true;
  in.pack_c = 30;
  in.bat_v = 11.5f;
  in.motors_on = true;
  in.vel_fresh = true;
  in.vel_ever = true;
  return in;
}

static bool unlimited(const motion::ReflexLimits& l) {
  return !l.block_all && !l.hard_stop && l.v_fwd_max > 1.0f && l.v_rev_max > 1.0f;
}

void test_calm_has_no_limits_or_fault() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  motion::ReflexLimits l = r.update(calm(1000), ev);
  TEST_ASSERT_TRUE(unlimited(l));
  TEST_ASSERT_NULL(r.fault());
  TEST_ASSERT_EQUAL(0, ev.size());
}

void test_bump_stops_and_holds_off_one_second() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  r.update(calm(1000), ev);
  Inputs in = calm(1020);
  in.bump_l = true;
  motion::ReflexLimits l = r.update(in, ev);
  TEST_ASSERT_TRUE(l.hard_stop);
  TEST_ASSERT_TRUE(l.estop);
  TEST_ASSERT_EQUAL_FLOAT(0, l.v_fwd_max);
  TEST_ASSERT_EQUAL_FLOAT(REFLEX_REVERSE_MAX, l.v_rev_max);
  TEST_ASSERT_TRUE(ev.contains("bump_l"));
  TEST_ASSERT_EQUAL_STRING("bump", r.fault());
  ev.clear();
  in.now_ms = 1040;  // still pressed: no new event, no new hard stop
  l = r.update(in, ev);
  TEST_ASSERT_FALSE(l.hard_stop);
  TEST_ASSERT_EQUAL(0, ev.size());
  // released at 1060; forward still refused until 2060
  l = r.update(calm(1060), ev);
  TEST_ASSERT_EQUAL_FLOAT(0, l.v_fwd_max);
  l = r.update(calm(2050), ev);
  TEST_ASSERT_EQUAL_FLOAT(0, l.v_fwd_max);
  l = r.update(calm(2061), ev);
  TEST_ASSERT_TRUE(unlimited(l));
  TEST_ASSERT_NULL(r.fault());
}

void test_drop_blocks_forward_until_clear() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  r.update(calm(1000), ev);
  Inputs in = calm(1020);
  in.drop[2] = true;
  motion::ReflexLimits l = r.update(in, ev);
  TEST_ASSERT_TRUE(l.hard_stop);
  TEST_ASSERT_TRUE(ev.contains("drop_r"));
  TEST_ASSERT_EQUAL_FLOAT(0, l.v_fwd_max);
  TEST_ASSERT_EQUAL_FLOAT(REFLEX_REVERSE_MAX, l.v_rev_max);
  TEST_ASSERT_EQUAL_STRING("drop", r.fault());
  l = r.update(calm(1040), ev);
  TEST_ASSERT_TRUE(unlimited(l));
}

void test_rear_drop_blocks_reverse_allows_slow_forward() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  r.update(calm(1000), ev);
  Inputs in = calm(1020);
  in.drop[1] = true;  // REAR sensor
  motion::ReflexLimits l = r.update(in, ev);
  TEST_ASSERT_TRUE(l.hard_stop);
  TEST_ASSERT_TRUE(ev.contains("drop_rear"));
  TEST_ASSERT_FALSE(ev.contains("drop_l"));
  TEST_ASSERT_EQUAL_FLOAT(0, l.v_rev_max);                    // no reverse
  TEST_ASSERT_EQUAL_FLOAT(REFLEX_REVERSE_MAX, l.v_fwd_max);   // creep forward away
  TEST_ASSERT_EQUAL_FLOAT(REFLEX_W_MAX, l.w_max);
  TEST_ASSERT_FALSE(l.block_all);
  TEST_ASSERT_EQUAL_STRING("drop", r.fault());
  l = r.update(calm(1040), ev);
  TEST_ASSERT_TRUE(unlimited(l));
}

void test_front_and_rear_drop_rotation_only() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  r.update(calm(980), ev);  // leave the boot state (no drop events for it)
  Inputs in = calm(1000);
  in.drop[0] = true;
  in.drop[1] = true;
  motion::ReflexLimits l = r.update(in, ev);
  TEST_ASSERT_EQUAL_FLOAT(0, l.v_fwd_max);
  TEST_ASSERT_EQUAL_FLOAT(0, l.v_rev_max);
  TEST_ASSERT_EQUAL_FLOAT(REFLEX_W_MAX, l.w_max);
  TEST_ASSERT_TRUE(ev.contains("drop_l"));
  TEST_ASSERT_TRUE(ev.contains("drop_rear"));
  // a front bump plus a rear drop is the same: nowhere to go but round
  Reflexes r2(defaultConfig());
  in = calm(1000);
  in.bump_r = true;
  in.drop[1] = true;
  l = r2.update(in, ev);
  TEST_ASSERT_EQUAL_FLOAT(0, l.v_fwd_max);
  TEST_ASSERT_EQUAL_FLOAT(0, l.v_rev_max);
  TEST_ASSERT_EQUAL_FLOAT(REFLEX_W_MAX, l.w_max);
}

void test_rear_drop_with_obstacle_ahead() {
  // rear drop allows 0.08 forward, an obstacle < 60 mm ahead takes that away
  Reflexes r(defaultConfig());
  EventQueue ev;
  Inputs in = calm(1000);
  in.drop[1] = true;
  in.fwd_mm[0] = 100;  // slow zone: cap 0.05 is below 0.08
  TEST_ASSERT_EQUAL_FLOAT(OBSTACLE_SLOW_V, r.update(in, ev).v_fwd_max);
  in.fwd_mm[0] = 40;
  TEST_ASSERT_EQUAL_FLOAT(0, r.update(in, ev).v_fwd_max);
}

void test_no_drop_events_for_boot_state() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  Inputs in = calm(10);
  in.drop[0] = in.drop[1] = in.drop[2] = true;  // detectors start as "drop"
  r.update(in, ev);
  TEST_ASSERT_FALSE(ev.contains("drop_l"));
  TEST_ASSERT_FALSE(ev.contains("drop_rear"));
  TEST_ASSERT_FALSE(ev.contains("drop_r"));
}

void test_drop_detector_margin_and_clear_time() {
  tof::DropDetector d(DROP_MARGIN_MM, DROP_CLEAR_MS);
  TEST_ASSERT_TRUE(d.drop());  // fail-safe at start
  TEST_ASSERT_TRUE(d.update(0, true, 40, 35));   // first good reading starts the clear timer
  TEST_ASSERT_TRUE(d.update(50, true, 40, 35));
  TEST_ASSERT_FALSE(d.update(100, true, 40, 35));
  TEST_ASSERT_FALSE(d.update(120, true, 95, 35));   // exactly floor+60: not a drop
  TEST_ASSERT_TRUE(d.update(140, true, 96, 35));    // floor+61: drop
  TEST_ASSERT_TRUE(d.update(160, false, 40, 35));   // invalid reading counts as drop
  TEST_ASSERT_TRUE(d.update(180, true, 40, 35));
  TEST_ASSERT_TRUE(d.update(279, true, 40, 35));
  TEST_ASSERT_FALSE(d.update(280, true, 40, 35));
  TEST_ASSERT_TRUE(d.update(300, true, 40, 35, true));  // forced (calibrating)
}

void test_down_and_forward_reading_classification() {
  TEST_ASSERT_TRUE(tof::downReadingOk(tof::RangeValid, true));
  TEST_ASSERT_FALSE(tof::downReadingOk(tof::RangeValid, false));  // stale
  TEST_ASSERT_FALSE(tof::downReadingOk(tof::SignalFail, true));   // nothing below = drop
  TEST_ASSERT_EQUAL(250, tof::forwardValue(tof::RangeValid, 250, true));
  TEST_ASSERT_EQUAL(tof::kNoTarget, tof::forwardValue(tof::SignalFail, 0, true));
  TEST_ASSERT_EQUAL(tof::kFault, tof::forwardValue(tof::HardwareFail, 0, true));
  TEST_ASSERT_EQUAL(tof::kFault, tof::forwardValue(tof::RangeValid, 100, false));
  TEST_ASSERT_EQUAL(0, tof::forwardValue(tof::MinRangeFail, 0, true));
}

void test_bumper_face_offset() {
  TEST_ASSERT_EQUAL(45, FWD_TOF_OFFSET_MM);
  TEST_ASSERT_EQUAL(60, tof::bumperDistance(105, FWD_TOF_OFFSET_MM));
  TEST_ASSERT_EQUAL(0, tof::bumperDistance(30, FWD_TOF_OFFSET_MM));
  TEST_ASSERT_EQUAL(tof::kNoTarget, tof::bumperDistance(tof::kNoTarget, FWD_TOF_OFFSET_MM));
  TEST_ASSERT_EQUAL(tof::kFault, tof::bumperDistance(tof::kFault, FWD_TOF_OFFSET_MM));
  // 150 mm at the sensor = 105 mm from the bumper -> slow; 100 at sensor = 55 -> stop
  Reflexes r(defaultConfig());
  EventQueue ev;
  Inputs in = calm(1000);
  in.fwd_mm[0] = tof::bumperDistance(150, FWD_TOF_OFFSET_MM);
  TEST_ASSERT_EQUAL_FLOAT(OBSTACLE_SLOW_V, r.update(in, ev).v_fwd_max);
  in.fwd_mm[0] = tof::bumperDistance(100, FWD_TOF_OFFSET_MM);
  TEST_ASSERT_EQUAL_FLOAT(0, r.update(in, ev).v_fwd_max);
}

void test_floor_calibration_median_and_rejection() {
  tof::FloorCal cal(CAL_SAMPLES, CAL_TIMEOUT_MS, CAL_MIN_MM, CAL_MAX_MM, FLOOR_DEFAULT_MM);
  TEST_ASSERT_EQUAL(FLOOR_DEFAULT_MM, cal.floorMm(0));
  cal.start(0);
  for (int i = 0; i < CAL_SAMPLES; i++) {
    cal.addSample(0, (i == 3) ? 900 : 50 + (i % 3));  // one wild outlier
    cal.addSample(1, 500);                            // too far: held in the air
    if (i < 4) cal.addSample(2, 53);                  // too few samples
  }
  TEST_ASSERT_FALSE(cal.tick(100));  // sensor 2 still short of samples
  TEST_ASSERT_TRUE(cal.running());
  TEST_ASSERT_TRUE(cal.tick(CAL_TIMEOUT_MS + 1));
  TEST_ASSERT_FALSE(cal.running());
  TEST_ASSERT_TRUE(cal.lastOk(0));
  TEST_ASSERT_EQUAL(51, cal.floorMm(0));  // median ignores the outlier
  TEST_ASSERT_FALSE(cal.lastOk(1));
  TEST_ASSERT_EQUAL(FLOOR_DEFAULT_MM, cal.floorMm(1));  // previous value kept
  TEST_ASSERT_FALSE(cal.lastOk(2));
}

void test_floor_calibration_rejects_step_edge_and_disagreement() {
  TEST_ASSERT_TRUE(CAL_MAX_MM <= 120);  // a sensor over a step must fall outside
  tof::FloorCal cal(CAL_SAMPLES, CAL_TIMEOUT_MS, CAL_MIN_MM, CAL_MAX_MM, FLOOR_DEFAULT_MM,
                    CAL_AGREE_MM);
  cal.start(0);
  for (int i = 0; i < CAL_SAMPLES; i++) {
    cal.addSample(0, 50);
    cal.addSample(1, 52);
    cal.addSample(2, 80);  // inside the window but 28 mm off the others: suspicious
  }
  TEST_ASSERT_TRUE(cal.tick(10));
  TEST_ASSERT_TRUE(cal.lastOk(0));
  TEST_ASSERT_TRUE(cal.lastOk(1));
  TEST_ASSERT_FALSE(cal.lastOk(2));
  TEST_ASSERT_EQUAL(FLOOR_DEFAULT_MM, cal.floorMm(2));
  // all three over a 150 mm step: all rejected (outside the window)
  cal.start(100);
  for (int i = 0; i < CAL_SAMPLES; i++)
    for (int s = 0; s < 3; s++) cal.addSample(s, 200);
  TEST_ASSERT_TRUE(cal.tick(110));
  for (int s = 0; s < 3; s++) TEST_ASSERT_FALSE(cal.lastOk(s));
  TEST_ASSERT_EQUAL(50, cal.floorMm(0));  // previous good value kept
}

void test_median() {
  tof::MedianCal m;
  int v[] = {5, 1, 4, 2, 3};
  for (int x : v) m.add(x);
  TEST_ASSERT_EQUAL(3, m.median());
  m.add(10);
  TEST_ASSERT_EQUAL(3, m.median());  // (3+4)/2 integer
}

void test_obstacle_slow_and_stop_with_hysteresis() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  Inputs in = calm(1000);
  in.fwd_mm[0] = 100;
  motion::ReflexLimits l = r.update(in, ev);
  TEST_ASSERT_EQUAL_FLOAT(OBSTACLE_SLOW_V, l.v_fwd_max);
  TEST_ASSERT_FALSE(l.estop);            // slow zone: ordinary a_max slow-down
  TEST_ASSERT_TRUE(l.v_rev_max > 1.0f);  // reverse not limited
  TEST_ASSERT_TRUE(ev.contains("obstacle"));
  TEST_ASSERT_EQUAL_STRING("obstacle", r.fault());
  in.fwd_mm[0] = 50;
  l = r.update(in, ev);
  TEST_ASSERT_EQUAL_FLOAT(0, l.v_fwd_max);
  TEST_ASSERT_TRUE(l.estop);  // < 60 mm: emergency brake
  in.fwd_mm[0] = 65;  // above 60 but inside hysteresis
  l = r.update(in, ev);
  TEST_ASSERT_EQUAL_FLOAT(0, l.v_fwd_max);
  in.fwd_mm[0] = 80;
  l = r.update(in, ev);
  TEST_ASSERT_EQUAL_FLOAT(OBSTACLE_SLOW_V, l.v_fwd_max);
  in.fwd_mm[0] = 125;  // inside slow hysteresis
  l = r.update(in, ev);
  TEST_ASSERT_EQUAL_FLOAT(OBSTACLE_SLOW_V, l.v_fwd_max);
  in.fwd_mm[0] = 140;
  l = r.update(in, ev);
  TEST_ASSERT_TRUE(unlimited(l));
}

void test_forward_sensor_fault_degrades_to_slow() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  Inputs in = calm(1000);
  in.fwd_mm[1] = tof::kFault;
  motion::ReflexLimits l = r.update(in, ev);
  TEST_ASSERT_EQUAL_FLOAT(OBSTACLE_SLOW_V, l.v_fwd_max);
  TEST_ASSERT_EQUAL_STRING("r sensor_fault", ev[0].detail);
}

void test_tilt_latches_until_upright_2s_and_torque_on() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  r.update(calm(1000), ev);
  Inputs in = calm(1020);
  in.pitch_deg = 30;
  motion::ReflexLimits l = r.update(in, ev);
  TEST_ASSERT_TRUE(l.torque_kill);
  TEST_ASSERT_TRUE(l.block_all);
  TEST_ASSERT_TRUE(ev.contains("tilt"));
  TEST_ASSERT_FALSE(r.requestTorqueOn(1040));  // still tilted
  // upright again from t=2000
  l = r.update(calm(2000), ev);
  TEST_ASSERT_TRUE(l.torque_kill);  // still latched without torque on
  r.update(calm(3000), ev);
  TEST_ASSERT_FALSE(r.requestTorqueOn(3000));  // only 1 s upright
  r.update(calm(4000), ev);
  TEST_ASSERT_TRUE(l.block_all);
  TEST_ASSERT_TRUE(r.requestTorqueOn(4000));  // 2 s upright + torque on
  l = r.update(calm(4020), ev);
  TEST_ASSERT_TRUE(unlimited(l));
  TEST_ASSERT_FALSE(r.tiltLatched());
}

void test_tilt_roll_and_imu_failure() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  Inputs in = calm(1000);
  in.roll_deg = -26;
  TEST_ASSERT_TRUE(r.update(in, ev).torque_kill);
  Reflexes r2(defaultConfig());
  ev.clear();
  in = calm(1000);
  in.imu_ok = false;
  TEST_ASSERT_TRUE(r2.update(in, ev).torque_kill);
  TEST_ASSERT_EQUAL_STRING("imu_fault", ev[0].detail);
  // 14 deg is not a tilt, 16 is (limit 15 deg, the tip point is ~19-21)
  TEST_ASSERT_EQUAL_FLOAT(15.0f, TILT_LIMIT_DEG);
  Reflexes r3(defaultConfig());
  in = calm(1000);
  in.roll_deg = 14;
  TEST_ASSERT_FALSE(r3.update(in, ev).torque_kill);
  in.now_ms = 1020;
  in.pitch_deg = -16;
  motion::ReflexLimits l3 = r3.update(in, ev);
  TEST_ASSERT_TRUE(l3.torque_kill);
  TEST_ASSERT_TRUE(l3.estop);  // braked at A_ESTOP before going limp
}

void test_tilt_requires_continuous_uprightness() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  Inputs in = calm(1000);
  in.pitch_deg = 40;
  r.update(in, ev);
  r.update(calm(1100), ev);  // upright from 1100
  in.now_ms = 2000;
  in.pitch_deg = 12;  // between 10 and 15: not tilted, but not "upright" either
  r.update(in, ev);
  r.update(calm(2500), ev);  // upright again from 2500
  TEST_ASSERT_FALSE(r.requestTorqueOn(3200));
  r.update(calm(4500), ev);
  TEST_ASSERT_TRUE(r.requestTorqueOn(4500));
}

void test_pack_hot_with_hysteresis() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  Inputs in = calm(1000);
  in.pack_c = 51;
  motion::ReflexLimits l = r.update(in, ev);
  TEST_ASSERT_TRUE(l.block_all);
  TEST_ASSERT_TRUE(l.estop);
  TEST_ASSERT_TRUE(l.hard_stop);
  TEST_ASSERT_TRUE(r.packHot());
  TEST_ASSERT_TRUE(ev.contains("pack_hot"));
  TEST_ASSERT_EQUAL_STRING("temp", ev[0].detail);
  TEST_ASSERT_EQUAL_STRING("pack_hot", r.fault());
  in.pack_c = 47;
  in.now_ms = 2000;
  TEST_ASSERT_TRUE(r.update(in, ev).block_all);
  in.pack_c = 44;
  in.now_ms = 3000;
  TEST_ASSERT_FALSE(r.update(in, ev).block_all);
}

void test_ntc_fault_and_bms_cutoff_count_as_pack_hot() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  Inputs in = calm(1000);
  in.ntc_ok = false;
  TEST_ASSERT_TRUE(r.update(in, ev).block_all);
  TEST_ASSERT_EQUAL_STRING("ntc_fault", ev[0].detail);
  Reflexes r2(defaultConfig());
  ev.clear();
  in = calm(1000);
  in.bat_v = 0.3f;
  TEST_ASSERT_TRUE(r2.update(in, ev).block_all);
  TEST_ASSERT_EQUAL_STRING("bms_cutoff", ev[0].detail);
}

void test_motors_off_blocks() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  Inputs in = calm(1000);
  in.motors_on = false;
  motion::ReflexLimits lm = r.update(in, ev);
  TEST_ASSERT_TRUE(lm.block_all);
  TEST_ASSERT_FALSE(lm.estop);  // no power to brake with: zero at once
  TEST_ASSERT_EQUAL_STRING("motors_off", r.fault());
  TEST_ASSERT_EQUAL(0, ev.size());
}

void test_watchdog_event_on_transition_only() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  Inputs in = calm(1000);
  in.vel_fresh = false;
  in.vel_ever = false;  // boot: no stream yet -> fault, but no event
  r.update(in, ev);
  TEST_ASSERT_EQUAL(0, ev.size());
  TEST_ASSERT_EQUAL_STRING("watchdog", r.fault());
  r.update(calm(1100), ev);
  TEST_ASSERT_NULL(r.fault());
  in = calm(1500);
  in.vel_fresh = false;
  TEST_ASSERT_FALSE(r.update(in, ev).estop);  // watchdog ramps at a_max
  TEST_ASSERT_TRUE(ev.contains("watchdog"));
  ev.clear();
  in.now_ms = 1600;
  r.update(in, ev);
  TEST_ASSERT_EQUAL(0, ev.size());
}

void test_fault_is_most_recent_active_reason() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  Inputs in = calm(1000);
  in.bump_r = true;
  r.update(in, ev);
  TEST_ASSERT_EQUAL_STRING("bump", r.fault());
  in.now_ms = 1100;
  in.fwd_mm[0] = 100;
  r.update(in, ev);
  TEST_ASSERT_EQUAL_STRING("obstacle", r.fault());
  in.now_ms = 1200;
  in.fwd_mm[0] = 500;  // obstacle gone, bump still held
  r.update(in, ev);
  TEST_ASSERT_EQUAL_STRING("bump", r.fault());
}

void test_wheel_servo_failure_blocks() {
  Reflexes r(defaultConfig());
  EventQueue ev;
  Inputs in = calm(1000);
  in.wheels_ok = false;
  TEST_ASSERT_TRUE(r.update(in, ev).block_all);
  TEST_ASSERT_EQUAL_STRING("servo_error", r.fault());
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_calm_has_no_limits_or_fault);
  RUN_TEST(test_bump_stops_and_holds_off_one_second);
  RUN_TEST(test_drop_blocks_forward_until_clear);
  RUN_TEST(test_rear_drop_blocks_reverse_allows_slow_forward);
  RUN_TEST(test_front_and_rear_drop_rotation_only);
  RUN_TEST(test_rear_drop_with_obstacle_ahead);
  RUN_TEST(test_no_drop_events_for_boot_state);
  RUN_TEST(test_drop_detector_margin_and_clear_time);
  RUN_TEST(test_down_and_forward_reading_classification);
  RUN_TEST(test_bumper_face_offset);
  RUN_TEST(test_floor_calibration_median_and_rejection);
  RUN_TEST(test_floor_calibration_rejects_step_edge_and_disagreement);
  RUN_TEST(test_median);
  RUN_TEST(test_obstacle_slow_and_stop_with_hysteresis);
  RUN_TEST(test_forward_sensor_fault_degrades_to_slow);
  RUN_TEST(test_tilt_latches_until_upright_2s_and_torque_on);
  RUN_TEST(test_tilt_roll_and_imu_failure);
  RUN_TEST(test_tilt_requires_continuous_uprightness);
  RUN_TEST(test_pack_hot_with_hysteresis);
  RUN_TEST(test_ntc_fault_and_bms_cutoff_count_as_pack_hot);
  RUN_TEST(test_motors_off_blocks);
  RUN_TEST(test_watchdog_event_on_transition_only);
  RUN_TEST(test_fault_is_most_recent_active_reason);
  RUN_TEST(test_wheel_servo_failure_blocks);
  return UNITY_END();
}
