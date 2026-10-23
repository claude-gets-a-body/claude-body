#pragma once
// TTP223 touch -> `pat` / `hold` / `double`. Hardware-free.
//   pat    = one short touch (reported after the double-tap window passes)
//   double = two short touches within the gap
//   hold   = touch held > hold_ms (reported the moment it qualifies)
#include <stdint.h>

namespace face {

enum Gesture : uint8_t { G_NONE = 0, G_PAT, G_HOLD, G_DOUBLE };
const char* gestureName(Gesture g);

class GestureDetector {
 public:
  GestureDetector(uint32_t debounce_ms, uint32_t hold_ms, uint32_t double_gap_ms)
      : deb_(debounce_ms), hold_(hold_ms), gap_(double_gap_ms) {}
  // raw: touch output (true = touched). Returns at most one gesture per call;
  // call again on the same tick if `pending()` (a pat + hold pair).
  Gesture update(bool raw, uint32_t now_ms);
  bool pending() const { return queued_ != G_NONE; }

 private:
  enum State : uint8_t { IDLE, PRESSED, WAIT_SECOND, HELD };
  uint32_t deb_, hold_, gap_;
  // debounce
  bool raw_ = false, stable_ = false;
  uint32_t raw_ms_ = 0;
  // gesture state
  State st_ = IDLE;
  bool second_ = false;
  uint32_t t0_ = 0;
  Gesture queued_ = G_NONE;
};

}  // namespace face
