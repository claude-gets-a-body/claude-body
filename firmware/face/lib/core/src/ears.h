#pragma once
// Ear pose controller: slew-limited motion towards a target, plus a wiggle
// animation. Hardware-free; output 0 (down) .. 1 (up) per ear.
#include <stdint.h>

namespace face {

class Ears {
 public:
  Ears(float slew_per_s, uint32_t wiggle_ms, float wiggle_hz, float wiggle_amp);
  void setTarget(float l, float r);
  void wiggle(uint32_t now_ms);
  // Advance to now; returns the poses to drive.
  void update(uint32_t now_ms, float out[2]);
  float target(int i) const { return target_[i]; }
  bool wiggling(uint32_t now_ms) const;

 private:
  float slew_, hz_, amp_;
  uint32_t wiggle_ms_;
  float target_[2] = {0.5f, 0.5f};
  float pos_[2] = {0.5f, 0.5f};
  uint32_t last_ms_ = 0, wiggle_start_ = 0;
  bool have_last_ = false, wiggle_on_ = false;
};

}  // namespace face
