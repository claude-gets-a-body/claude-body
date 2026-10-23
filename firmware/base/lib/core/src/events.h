#pragma once
// Small fixed-size queue of outgoing `event` messages. Hardware-free.
#include <stdint.h>
#include <string.h>

struct Event {
  const char* e;      // static string, one of the PROTOCOL event names
  char detail[40];    // "" = no detail
};

class EventQueue {
 public:
  static const int kMax = 16;
  void push(const char* e, const char* detail = "") {
    if (n_ >= kMax) return;  // drop rather than block
    ev_[n_].e = e;
    strncpy(ev_[n_].detail, detail ? detail : "", sizeof(ev_[n_].detail) - 1);
    ev_[n_].detail[sizeof(ev_[n_].detail) - 1] = 0;
    n_++;
  }
  int size() const { return n_; }
  const Event& operator[](int i) const { return ev_[i]; }
  void clear() { n_ = 0; }
  bool contains(const char* e) const {
    for (int i = 0; i < n_; i++)
      if (strcmp(ev_[i].e, e) == 0) return true;
    return false;
  }

 private:
  Event ev_[kMax];
  int n_ = 0;
};
