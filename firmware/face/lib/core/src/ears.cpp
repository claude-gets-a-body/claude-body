#include "ears.h"

#include <math.h>

namespace face {

static float clamp01(float x) { return x < 0 ? 0 : (x > 1 ? 1 : x); }

Ears::Ears(float slew_per_s, uint32_t wiggle_ms, float wiggle_hz, float wiggle_amp)
    : slew_(slew_per_s), hz_(wiggle_hz), amp_(wiggle_amp), wiggle_ms_(wiggle_ms) {}

void Ears::setTarget(float l, float r) {
  if (l == l) target_[0] = clamp01(l);
  if (r == r) target_[1] = clamp01(r);
}

void Ears::wiggle(uint32_t now) {
  wiggle_on_ = true;
  wiggle_start_ = now;
}

bool Ears::wiggling(uint32_t now) const {
  return wiggle_on_ && (uint32_t)(now - wiggle_start_) < wiggle_ms_;
}

void Ears::update(uint32_t now, float out[2]) {
  const float dt = have_last_ ? (float)(uint32_t)(now - last_ms_) / 1000.0f : 0;
  have_last_ = true;
  last_ms_ = now;
  const float step = slew_ * (dt > 0.2f ? 0.2f : dt);
  for (int i = 0; i < 2; i++) {
    const float d = target_[i] - pos_[i];
    pos_[i] += d > step ? step : (d < -step ? -step : d);
  }
  float w = 0;
  if (wiggling(now)) {
    const float t = (float)(uint32_t)(now - wiggle_start_) / 1000.0f;
    const float fade = 1.0f - t * 1000.0f / (float)wiggle_ms_;  // taper off
    w = amp_ * fade * sinf(6.2831853f * hz_ * t);
  } else {
    wiggle_on_ = false;
  }
  // opposite phase: one ear up while the other goes down
  out[0] = clamp01(pos_[0] + w);
  out[1] = clamp01(pos_[1] - w);
}

}  // namespace face
