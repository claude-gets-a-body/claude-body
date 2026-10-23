// Mood tables, transitions, eye geometry, blink scheduler, ears.
#include <math.h>
#include <string.h>
#include <unity.h>

#include "blink.h"
#include "config.h"
#include "ears.h"
#include "eye_geom.h"
#include "moods.h"

using namespace face;

void setUp() {}
void tearDown() {}

static EyeGeom geom(const EyePose& p, float gx, float gy, float blink, int side) {
  return eyeGeometry(p, gx, gy, blink, side, 1.0f, EYE_SIZE, GAZE_MAX_X_PX, GAZE_MAX_Y_PX);
}
static float openGap(const EyeGeom& g) {  // visible height at the disc centre column
  return botLidY(g, g.cx) - topLidY(g, g.cx);
}

void test_all_protocol_moods_exist() {
  const char* names[] = {"neutral", "happy", "curious",  "thinking", "sad",
                         "surprised", "sleepy", "asleep", "confused", "listening"};
  for (int i = 0; i < 10; i++) {
    Mood m;
    TEST_ASSERT_TRUE_MESSAGE(moodFromName(names[i], m), names[i]);
    TEST_ASSERT_EQUAL_STRING(names[i], moodName(m));
  }
  Mood m;
  TEST_ASSERT_FALSE(moodFromName("angry", m));
  TEST_ASSERT_FALSE(moodFromName(nullptr, m));
}

void test_pose_table_sane() {
  for (int i = 0; i < MOOD_COUNT; i++) {
    const FacePose& p = moodPose((Mood)i);
    for (int e = 0; e < 2; e++) {
      TEST_ASSERT_TRUE(p.eye[e].iris_r >= 50 && p.eye[e].iris_r <= 100);
      TEST_ASSERT_TRUE(p.eye[e].lid_top >= 0 && p.eye[e].lid_top <= 1);
      TEST_ASSERT_TRUE(p.eye[e].lid_bot >= 0 && p.eye[e].lid_bot <= 1);
      TEST_ASSERT_TRUE(p.ear[e] >= 0 && p.ear[e] <= 1);
      // the iris must fit the round screen
      TEST_ASSERT_TRUE(p.eye[e].iris_r < EYE_SIZE / 2 - 4);
    }
  }
  // character checks: the moods mean what they say
  TEST_ASSERT_TRUE(moodPose(ASLEEP).closed);
  TEST_ASSERT_FALSE(moodPose(NEUTRAL).closed);
  TEST_ASSERT_TRUE(moodPose(SURPRISED).eye[0].iris_r > moodPose(NEUTRAL).eye[0].iris_r);
  TEST_ASSERT_TRUE(moodPose(SAD).eye[0].lid_tilt < 0);       // outer corners droop
  TEST_ASSERT_TRUE(moodPose(HAPPY).eye[0].smile > 0.5f);     // crescent
  TEST_ASSERT_TRUE(moodPose(HAPPY).wiggle);
  TEST_ASSERT_EQUAL_FLOAT(1.0f, moodPose(LISTENING).ear[0]); // ears up = listening
  TEST_ASSERT_TRUE(moodPose(SLEEPY).ear[0] < 0.3f);          // ears down = sleepy
  TEST_ASSERT_TRUE(moodPose(SLEEPY).eye[0].lid_top > 0.4f);
  TEST_ASSERT_EQUAL_FLOAT(0.5f, moodPose(NEUTRAL).ear[0]);   // half = idle
  // confused and curious are asymmetric
  TEST_ASSERT_TRUE(moodPose(CONFUSED).eye[0].lid_top != moodPose(CONFUSED).eye[1].lid_top);
  TEST_ASSERT_TRUE(moodPose(CURIOUS).eye[0].iris_r != moodPose(CURIOUS).eye[1].iris_r);
}

void test_transition_is_smooth_and_starts_mid_way() {
  MoodBlender b;
  b.set(SURPRISED, 1000, 300);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, moodPose(NEUTRAL).eye[0].iris_r, b.at(1000).eye[0].iris_r);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, moodPose(SURPRISED).eye[0].iris_r, b.at(1300).eye[0].iris_r);
  float prev = 0;
  for (uint32_t t = 1000; t <= 1300; t += 10) {  // monotonic, no jumps
    const float r = b.at(t).eye[0].iris_r;
    TEST_ASSERT_TRUE(r >= prev - 1e-4f);
    if (t > 1000) TEST_ASSERT_TRUE(r - prev < 3.0f);
    prev = r;
  }
  // interrupting mid-way continues from the current pose, no snap
  const float mid = b.at(1150).eye[0].iris_r;
  b.set(SAD, 1150, 300);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, mid, b.at(1150).eye[0].iris_r);
  TEST_ASSERT_EQUAL(SAD, b.mood());
  // zero-time transition snaps
  b.set(HAPPY, 2000, 0);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, moodPose(HAPPY).eye[0].smile, b.at(2000).eye[0].smile);
}

void test_easing() {
  TEST_ASSERT_EQUAL_FLOAT(0, easeInOut(-1));
  TEST_ASSERT_EQUAL_FLOAT(1, easeInOut(2));
  TEST_ASSERT_FLOAT_WITHIN(1e-6, 0.5f, easeInOut(0.5f));
  TEST_ASSERT_TRUE(easeInOut(0.1f) < 0.1f);  // slow start
  TEST_ASSERT_TRUE(easeInOut(0.9f) > 0.9f);  // slow end
}

void test_gaze_direction_mapping() {
  const EyePose& n = moodPose(NEUTRAL).eye[0];
  EyeGeom c = geom(n, 0, 0, 0, 0);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, 120, c.cx);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, 120, c.cy);
  // robot looks to ITS left: pupils move to screen +x (the viewer's right)
  EyeGeom l = geom(n, -1, 0, 0, 0);
  TEST_ASSERT_TRUE(l.cx > c.cx + 20);
  EyeGeom u = geom(n, 0, 1, 0, 1);  // up -> screen -y
  TEST_ASSERT_TRUE(u.cy < c.cy - 15);
  // corners: never leaves the round glass
  for (int i = 0; i < MOOD_COUNT; i++)
    for (int s = 0; s < 2; s++) {
      const EyePose& p = moodPose((Mood)i).eye[s];
      EyeGeom g = geom(p, 1, -1, 0, s);
      const float d = sqrtf((g.cx - 120) * (g.cx - 120) + (g.cy - 120) * (g.cy - 120));
      TEST_ASSERT_TRUE(d + g.r <= 120);
    }
}

void test_blink_closes_every_mood() {
  for (int i = 0; i < MOOD_COUNT; i++) {
    for (int s = 0; s < 2; s++) {
      const EyePose& p = moodPose((Mood)i).eye[s];
      EyeGeom g = geom(p, 0, 0, 1.0f, s);
      TEST_ASSERT_TRUE_MESSAGE(g.closed, moodName((Mood)i));
      EyeGeom half = geom(p, 0, 0, 0.5f, s);
      EyeGeom open = geom(p, 0, 0, 0.0f, s);
      if (!open.closed) TEST_ASSERT_TRUE(openGap(half) < openGap(open));
    }
  }
}

void test_asleep_is_closed_without_blinking() {
  EyeGeom g = geom(moodPose(ASLEEP).eye[0], 0, 0, 0, 0);
  TEST_ASSERT_TRUE(g.closed);
  EyeGeom n = geom(moodPose(NEUTRAL).eye[0], 0, 0, 0, 0);
  TEST_ASSERT_FALSE(n.closed);
  TEST_ASSERT_TRUE(openGap(n) > 1.5f * n.r);  // neutral is properly open
}

void test_lid_tilt_and_smile_shapes() {
  // sad: outer corner lower than inner corner (robot's left eye: inner = screen -x)
  EyeGeom s = geom(moodPose(SAD).eye[0], 0, 0, 0, 0);
  const float inner = topLidY(s, s.cx - 0.8f * s.r), outer = topLidY(s, s.cx + 0.8f * s.r);
  TEST_ASSERT_TRUE(outer > inner + 5);
  // mirrored on the other eye
  EyeGeom s2 = geom(moodPose(SAD).eye[1], 0, 0, 0, 1);
  TEST_ASSERT_TRUE(topLidY(s2, s2.cx - 0.8f * s2.r) > topLidY(s2, s2.cx + 0.8f * s2.r) + 5);
  // happy: the bottom lid rises in the middle (crescent)
  EyeGeom h = geom(moodPose(HAPPY).eye[0], 0, 0, 0, 0);
  TEST_ASSERT_TRUE(botLidY(h, h.cx) < botLidY(h, h.cx + 0.9f * h.r) - 20);
  TEST_ASSERT_TRUE(openGap(h) > 0);  // still visible
}

void test_blink_schedule_intervals_and_doubles() {
  Blinker b(defaultBlinkTiming(), 12345);
  b.start(0);
  uint32_t last_end = 0;
  bool in = false;
  int singles = 0, doubles = 0;
  uint32_t last_start = 0;
  for (uint32_t t = 0; t < 600000; t += 5) {  // 10 minutes
    const float c = b.closure(t);
    TEST_ASSERT_TRUE(c >= 0 && c <= 1);
    if (c > 0 && !in) {
      in = true;
      const uint32_t gap = t - last_end;
      if (last_start) {
        if (gap <= BLINK_DOUBLE_GAP_MS + 10) doubles++;
        else {
          singles++;
          TEST_ASSERT_TRUE(gap >= BLINK_MIN_MS - 10 && gap <= BLINK_MAX_MS + 10);
        }
      }
      last_start = t;
    }
    if (c == 0 && in) {
      in = false;
      last_end = t;
    }
  }
  // ~4 s average -> ~150 blinks in 10 min, a few of them doubles
  TEST_ASSERT_TRUE(singles > 90 && singles < 220);
  TEST_ASSERT_TRUE(doubles > 3);
  TEST_ASSERT_TRUE(doubles < singles / 2);
}

void test_blink_shape_and_manual_trigger() {
  BlinkTiming t = defaultBlinkTiming();
  Blinker b(t, 1);
  b.setAuto(false, 0);
  TEST_ASSERT_EQUAL_FLOAT(0, b.closure(100000));  // no auto blinks when disabled
  b.trigger(1000);
  TEST_ASSERT_TRUE(b.closure(1000 + t.close_ms / 2) > 0.1f);
  TEST_ASSERT_EQUAL_FLOAT(1, b.closure(1000 + t.close_ms + 1));
  TEST_ASSERT_TRUE(b.closure(1000 + t.close_ms + t.hold_ms + t.open_ms / 2) < 1);
  TEST_ASSERT_EQUAL_FLOAT(0, b.closure(1000 + t.close_ms + t.hold_ms + t.open_ms + 1));
  TEST_ASSERT_FALSE(b.blinking());
  const uint32_t total = t.close_ms + t.hold_ms + t.open_ms;
  TEST_ASSERT_TRUE(total < 300);  // a blink must be quick
}

void test_ears_slew_and_wiggle() {
  Ears e(EAR_SLEW_PER_S, EAR_WIGGLE_MS, EAR_WIGGLE_HZ, EAR_WIGGLE_AMP);
  float o[2];
  e.update(0, o);
  TEST_ASSERT_FLOAT_WITHIN(1e-4, 0.5f, o[0]);
  e.setTarget(1.0f, 0.0f);
  e.update(100, o);  // 0.1 s at 2.5/s = 0.25 max
  TEST_ASSERT_FLOAT_WITHIN(1e-3, 0.75f, o[0]);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, 0.25f, o[1]);
  for (uint32_t t = 120; t < 1000; t += 20) e.update(t, o);
  TEST_ASSERT_FLOAT_WITHIN(1e-4, 1.0f, o[0]);
  TEST_ASSERT_FLOAT_WITHIN(1e-4, 0.0f, o[1]);
  e.setTarget(0.5f, 0.5f);
  for (uint32_t t = 1000; t < 2000; t += 20) e.update(t, o);
  e.wiggle(2000);
  float lo = 1, hi = 0;
  for (uint32_t t = 2000; t < 2000 + EAR_WIGGLE_MS; t += 10) {
    e.update(t, o);
    lo = fminf(lo, o[0]);
    hi = fmaxf(hi, o[0]);
    TEST_ASSERT_FLOAT_WITHIN(1e-4, 1.0f - o[0], o[1]);  // opposite phase about 0.5
  }
  TEST_ASSERT_TRUE(hi - lo > 0.15f);
  e.update(2000 + EAR_WIGGLE_MS + 50, o);
  TEST_ASSERT_FLOAT_WITHIN(1e-4, 0.5f, o[0]);  // settled after the wiggle
  e.setTarget(7.0f, -3.0f);                    // clamped
  TEST_ASSERT_EQUAL_FLOAT(1.0f, e.target(0));
  TEST_ASSERT_EQUAL_FLOAT(0.0f, e.target(1));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_all_protocol_moods_exist);
  RUN_TEST(test_pose_table_sane);
  RUN_TEST(test_transition_is_smooth_and_starts_mid_way);
  RUN_TEST(test_easing);
  RUN_TEST(test_gaze_direction_mapping);
  RUN_TEST(test_blink_closes_every_mood);
  RUN_TEST(test_asleep_is_closed_without_blinking);
  RUN_TEST(test_lid_tilt_and_smile_shapes);
  RUN_TEST(test_blink_schedule_intervals_and_doubles);
  RUN_TEST(test_blink_shape_and_manual_trigger);
  RUN_TEST(test_ears_slew_and_wiggle);
  return UNITY_END();
}
