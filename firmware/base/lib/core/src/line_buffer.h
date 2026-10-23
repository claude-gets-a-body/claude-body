#pragma once
// Accumulates bytes into newline-terminated lines. Over-long lines are
// discarded whole (never parsed as a truncated, possibly wrong, command).
// Hardware-free.
#include <stddef.h>

template <size_t N>
class LineBuffer {
 public:
  // Feed one byte. Returns true when a complete line is ready in line().
  bool push(char c) {
    if (c == '\r') return false;
    if (c == '\n') {
      const bool ok = !overflow_ && len_ > 0;
      buf_[len_] = 0;
      ready_len_ = ok ? len_ : 0;
      len_ = 0;
      overflow_ = false;
      return ok;
    }
    if (overflow_) return false;
    if (len_ >= N - 1) {
      overflow_ = true;
      len_ = 0;
      overflows_++;
      return false;
    }
    buf_[len_++] = c;
    return false;
  }
  const char* line() const { return buf_; }
  size_t length() const { return ready_len_; }
  unsigned overflows() const { return overflows_; }

 private:
  char buf_[N];
  size_t len_ = 0, ready_len_ = 0;
  bool overflow_ = false;
  unsigned overflows_ = 0;
};
