#include "blink.h"

#include "config.h"

namespace face {

BlinkTiming defaultBlinkTiming() {
  return BlinkTiming{BLINK_MIN_MS,   BLINK_MAX_MS,  BLINK_DOUBLE_PCT,   BLINK_CLOSE_MS,
                     BLINK_HOLD_MS, BLINK_OPEN_MS, BLINK_DOUBLE_GAP_MS};
}

Blinker::Blinker(const BlinkTiming& t, uint32_t seed) : t_(t), state_(seed ? seed : 0x9E3779B9u) {}

uint32_t Blinker::rnd() {  // xorshift32
  state_ ^= state_ << 13;
  state_ ^= state_ >> 17;
  state_ ^= state_ << 5;
  return state_;
}

void Blinker::scheduleNext(uint32_t now) {
  const uint32_t span = t_.max_ms > t_.min_ms ? t_.max_ms - t_.min_ms : 1;
  next_ = now + t_.min_ms + rnd() % span;
}

void Blinker::start(uint32_t now) { scheduleNext(now); }

void Blinker::trigger(uint32_t now) {
  in_blink_ = true;
  blink_start_ = now;
  count_++;
}

void Blinker::setAuto(bool on, uint32_t now) {
  if (on && !auto_) scheduleNext(now);
  auto_ = on;
  if (!on) double_pending_ = false;
}

static float easeIn(float t) { return t * t; }
static float easeOut(float t) { return 1 - (1 - t) * (1 - t); }

float Blinker::closure(uint32_t now) {
  if (!in_blink_) {
    if (auto_ && (int32_t)(now - next_) >= 0) {
      double_pending_ = double_pending_ ? false : (rnd() % 100) < t_.double_pct;
      trigger(now);
    } else {
      return 0;
    }
  }
  const uint32_t e = now - blink_start_;
  const uint32_t total = t_.close_ms + t_.hold_ms + t_.open_ms;
  if (e < t_.close_ms) return easeIn((float)e / t_.close_ms);
  if (e < t_.close_ms + t_.hold_ms) return 1;
  if (e < total) return 1 - easeOut((float)(e - t_.close_ms - t_.hold_ms) / t_.open_ms);
  // blink finished
  in_blink_ = false;
  if (double_pending_ && auto_) {
    next_ = now + t_.double_gap_ms;  // second half of a double blink
  } else {
    double_pending_ = false;
    scheduleNext(now);
  }
  return 0;
}

}  // namespace face
