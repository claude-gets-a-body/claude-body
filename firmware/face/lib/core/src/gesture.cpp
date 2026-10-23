#include "gesture.h"

namespace face {

const char* gestureName(Gesture g) {
  switch (g) {
    case G_PAT:
      return "pat";
    case G_HOLD:
      return "hold";
    case G_DOUBLE:
      return "double";
    default:
      return nullptr;
  }
}

Gesture GestureDetector::update(bool raw, uint32_t now) {
  if (queued_ != G_NONE) {
    const Gesture g = queued_;
    queued_ = G_NONE;
    return g;
  }
  if (raw != raw_) {
    raw_ = raw;
    raw_ms_ = now;
  }
  const bool prev = stable_;
  if (raw_ != stable_ && (uint32_t)(now - raw_ms_) >= deb_) stable_ = raw_;
  const bool pressed = stable_ && !prev;
  const bool released = !stable_ && prev;

  switch (st_) {
    case IDLE:
      if (pressed) {
        st_ = PRESSED;
        second_ = false;
        t0_ = now;
      }
      break;
    case PRESSED:
      if (released) {
        if (second_) {
          st_ = IDLE;
          return G_DOUBLE;
        }
        st_ = WAIT_SECOND;
        t0_ = now;
      } else if ((uint32_t)(now - t0_) >= hold_) {
        st_ = HELD;
        if (second_) {  // tap, then press-and-hold: report both
          queued_ = G_HOLD;
          return G_PAT;
        }
        return G_HOLD;
      }
      break;
    case WAIT_SECOND:
      if (pressed) {
        st_ = PRESSED;
        second_ = true;
        t0_ = now;
      } else if ((uint32_t)(now - t0_) >= gap_) {
        st_ = IDLE;
        return G_PAT;
      }
      break;
    case HELD:
      if (released) st_ = IDLE;
      break;
  }
  return G_NONE;
}

}  // namespace face
