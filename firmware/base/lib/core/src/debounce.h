#pragma once
// Asymmetric time-based debouncer: a press is accepted fast (safety), a
// release only after the contact has been stable for longer. Hardware-free.
#include <stdint.h>

class Debouncer {
 public:
  Debouncer(uint32_t press_ms, uint32_t release_ms) : press_ms_(press_ms), release_ms_(release_ms) {}
  // raw: true = contact closed. Returns the debounced state.
  bool update(bool raw, uint32_t now_ms) {
    if (raw != raw_) {
      raw_ = raw;
      changed_ms_ = now_ms;
    }
    if (raw_ != state_) {
      const uint32_t need = raw_ ? press_ms_ : release_ms_;
      if ((uint32_t)(now_ms - changed_ms_) >= need) state_ = raw_;
    }
    return state_;
  }
  bool state() const { return state_; }
  void force(bool s) { state_ = raw_ = s; }

 private:
  uint32_t press_ms_, release_ms_;
  bool raw_ = false, state_ = false;
  uint32_t changed_ms_ = 0;
};
