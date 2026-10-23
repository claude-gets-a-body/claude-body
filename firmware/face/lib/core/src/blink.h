#pragma once
// Blink scheduler: auto-blinks every BLINK_MIN..MAX ms, sometimes a double
// blink, plus on-demand blinks. Hardware-free (seeded PRNG for tests).
#include <stdint.h>

namespace face {

struct BlinkTiming {
  uint32_t min_ms, max_ms;
  uint32_t double_pct;
  uint32_t close_ms, hold_ms, open_ms, double_gap_ms;
};
BlinkTiming defaultBlinkTiming();  // from config.h

class Blinker {
 public:
  Blinker(const BlinkTiming& t, uint32_t seed);
  void start(uint32_t now_ms);           // schedule the first auto blink
  void trigger(uint32_t now_ms);         // blink right now
  void setAuto(bool on, uint32_t now_ms);
  // Lid closure 0..1 for this instant (also advances the schedule).
  float closure(uint32_t now_ms);
  bool blinking() const { return in_blink_; }
  uint32_t nextAt() const { return next_; }
  uint32_t blinkCount() const { return count_; }

 private:
  uint32_t rnd();
  void scheduleNext(uint32_t now_ms);
  BlinkTiming t_;
  uint32_t state_;
  bool auto_ = true;
  bool in_blink_ = false;
  bool double_pending_ = false;
  uint32_t blink_start_ = 0, next_ = 0, count_ = 0;
};

}  // namespace face
