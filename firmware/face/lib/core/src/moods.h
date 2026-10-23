#pragma once
// Mood -> eye/ear pose presets, and smooth transitions between them.
// Hardware-free. The renderer (src/eyes.cpp) turns an EyePose into pixels.
#include <stdint.h>

namespace face {

enum Mood : uint8_t {
  NEUTRAL = 0,
  HAPPY,
  CURIOUS,
  THINKING,
  SAD,
  SURPRISED,
  SLEEPY,
  ASLEEP,
  CONFUSED,
  LISTENING,
  MOOD_COUNT
};
bool moodFromName(const char* name, Mood& out);
const char* moodName(Mood m);

// One eye. Lid fractions are of the iris height: lid_top 0 = fully open at
// the top, lid_top + lid_bot >= 1 = closed.
struct EyePose {
  float iris_r;    // px
  float lid_top;   // 0..1 covered from the top
  float lid_bot;   // 0..1 covered from the bottom
  float lid_tilt;  // -1..1: + = inner (nose-side) corner lower (focused),
                   //         - = outer corner lower (sad)
  float smile;     // 0..1: bottom lid arcs up into a happy "^" crescent
  float gaze_x;    // bias added to the Pi's gaze, -1..1 (- = robot's left)
  float gaze_y;    //                                 (- = down)
};

struct FacePose {
  EyePose eye[2];  // [0] = robot's left eye, [1] = robot's right eye
  float ear[2];    // 0 = down, 1 = up
  bool wiggle;     // wiggle the ears on entering this mood
  bool closed;     // asleep: no auto-blink, breathing backlight
};

const FacePose& moodPose(Mood m);

float lerp(float a, float b, float t);
float easeInOut(float t);  // cubic, 0..1 -> 0..1
EyePose lerpEye(const EyePose& a, const EyePose& b, float t);
FacePose lerpPose(const FacePose& a, const FacePose& b, float t);

// Eased transition from the current (possibly mid-transition) pose to a new one.
class MoodBlender {
 public:
  MoodBlender();
  void set(Mood m, uint32_t now_ms, uint32_t duration_ms);
  FacePose at(uint32_t now_ms) const;
  Mood mood() const { return mood_; }
  bool done(uint32_t now_ms) const { return (uint32_t)(now_ms - start_) >= dur_; }

 private:
  FacePose from_, to_;
  uint32_t start_ = 0, dur_ = 0;
  Mood mood_ = NEUTRAL;
};

}  // namespace face
