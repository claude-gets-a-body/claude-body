#include "moods.h"

#include <string.h>

namespace face {

static const char* const kNames[MOOD_COUNT] = {"neutral",   "happy",  "curious", "thinking",
                                               "sad",       "surprised", "sleepy", "asleep",
                                               "confused", "listening"};

bool moodFromName(const char* name, Mood& out) {
  if (!name) return false;
  for (int i = 0; i < MOOD_COUNT; i++)
    if (strcmp(name, kNames[i]) == 0) {
      out = (Mood)i;
      return true;
    }
  return false;
}

const char* moodName(Mood m) { return m < MOOD_COUNT ? kNames[m] : "neutral"; }

// Two equal eyes
#define SYM(r, top, bot, tilt, smile, gx, gy) \
  {{r, top, bot, tilt, smile, gx, gy}, {r, top, bot, tilt, smile, gx, gy}}

// Design notes: big round eyes read as friendly; expressions come mostly from
// the lids, the way a cartoon or a puppy does it. Never fully wide-open
// staring except "surprised", and even then it blinks.
static const FacePose kPoses[MOOD_COUNT] = {
    // NEUTRAL: relaxed, lids barely in the frame
    {SYM(72, 0.10f, 0.04f, 0.0f, 0.0f, 0, 0), {0.5f, 0.5f}, false, false},
    // HAPPY: smiling crescents, ears perky and wiggling
    {SYM(74, 0.04f, 0.00f, 0.0f, 0.85f, 0, 0.05f), {0.85f, 0.85f}, true, false},
    // CURIOUS: one eye opened wider, the other a little narrowed; head-tilt feel
    {{{78, 0.00f, 0.00f, 0.0f, 0.0f, 0.10f, 0.08f}, {70, 0.22f, 0.02f, 0.30f, 0.0f, 0.10f, 0.08f}},
     {0.9f, 0.6f},
     false,
     false},
    // THINKING: looks up and to one side, lids slightly lowered
    {SYM(66, 0.26f, 0.04f, -0.15f, 0.0f, 0.45f, 0.45f), {0.6f, 0.4f}, false, false},
    // SAD: outer corners droop, eyes lower, ears down
    {SYM(70, 0.30f, 0.04f, -0.60f, 0.0f, 0, -0.25f), {0.15f, 0.15f}, false, false},
    // SURPRISED: big eyes, no lids, ears straight up
    {SYM(86, 0.00f, 0.00f, 0.0f, 0.0f, 0, 0.05f), {1.0f, 1.0f}, false, false},
    // SLEEPY: heavy lids
    {SYM(70, 0.52f, 0.12f, -0.10f, 0.0f, 0, -0.15f), {0.2f, 0.2f}, false, false},
    // ASLEEP: closed (meet at 62 % of the height), ears down
    {SYM(70, 0.62f, 0.38f, 0.0f, 0.0f, 0, -0.1f), {0.0f, 0.0f}, false, true},
    // CONFUSED: asymmetric: one lid down and tilted, the other wide
    {{{72, 0.30f, 0.04f, 0.35f, 0.0f, -0.08f, 0}, {76, 0.02f, 0.00f, -0.20f, 0.0f, -0.08f, 0}},
     {0.8f, 0.3f},
     false,
     false},
    // LISTENING: open, attentive, ears up
    {SYM(78, 0.02f, 0.00f, 0.0f, 0.0f, 0, 0.05f), {1.0f, 1.0f}, false, false},
};

const FacePose& moodPose(Mood m) { return kPoses[m < MOOD_COUNT ? m : NEUTRAL]; }

float lerp(float a, float b, float t) { return a + (b - a) * t; }

float easeInOut(float t) {
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  return t < 0.5f ? 4 * t * t * t : 1 - (-2 * t + 2) * (-2 * t + 2) * (-2 * t + 2) / 2;
}

EyePose lerpEye(const EyePose& a, const EyePose& b, float t) {
  EyePose e;
  e.iris_r = lerp(a.iris_r, b.iris_r, t);
  e.lid_top = lerp(a.lid_top, b.lid_top, t);
  e.lid_bot = lerp(a.lid_bot, b.lid_bot, t);
  e.lid_tilt = lerp(a.lid_tilt, b.lid_tilt, t);
  e.smile = lerp(a.smile, b.smile, t);
  e.gaze_x = lerp(a.gaze_x, b.gaze_x, t);
  e.gaze_y = lerp(a.gaze_y, b.gaze_y, t);
  return e;
}

FacePose lerpPose(const FacePose& a, const FacePose& b, float t) {
  FacePose p;
  for (int i = 0; i < 2; i++) {
    p.eye[i] = lerpEye(a.eye[i], b.eye[i], t);
    p.ear[i] = lerp(a.ear[i], b.ear[i], t);
  }
  p.wiggle = b.wiggle;
  p.closed = t >= 1.0f ? b.closed : (a.closed && b.closed);
  return p;
}

MoodBlender::MoodBlender() : from_(kPoses[NEUTRAL]), to_(kPoses[NEUTRAL]) {}

void MoodBlender::set(Mood m, uint32_t now, uint32_t duration_ms) {
  from_ = at(now);  // start from wherever we are, even mid-transition
  to_ = moodPose(m);
  mood_ = m;
  start_ = now;
  dur_ = duration_ms;
}

FacePose MoodBlender::at(uint32_t now) const {
  if (dur_ == 0) return to_;
  const float t = (float)(uint32_t)(now - start_) / (float)dur_;
  return lerpPose(from_, to_, easeInOut(t > 1 ? 1 : t));
}

}  // namespace face
