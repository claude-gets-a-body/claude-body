#include "visor.h"

namespace face {

const char* visorName(VisorReport r) {
  switch (r) {
    case V_CLOSED:
      return "closed";
    case V_MOVING:
      return "moving";
    case V_OPEN:
      return "open";
    default:
      return "jammed";
  }
}

void Visor::setReport(VisorReport r) {
  if (r != report_) {
    report_ = r;
    changed_ = true;
  }
}

void Visor::startClose(uint32_t now, VisorReport r) {
  st_ = CLOSING;
  servo_open_ = false;
  t0_ = now;
  setReport(r);
}

void Visor::boot(uint32_t now) {
  report_ = V_CLOSED;  // force a change so `moving` is announced
  startClose(now, V_MOVING);
}

void Visor::command(bool open, uint32_t now) {
  if (open) {
    if (st_ == OPEN || st_ == OPENING) return;
    st_ = OPENING;
    servo_open_ = true;
    t0_ = now;
    setReport(V_MOVING);
  } else {
    if (st_ == CLOSED || st_ == CLOSING || st_ == STUCK_UP) return;
    startClose(now, V_MOVING);
  }
}

void Visor::update(bool up, uint32_t now) {
  switch (st_) {
    case OPENING:
      if (up) {
        st_ = OPEN;
        setReport(V_OPEN);
      } else if ((uint32_t)(now - t0_) >= open_to_) {
        startClose(now, V_JAMMED);  // didn't make it up: report and close again
      }
      break;
    case OPEN:
      if (!up) startClose(now, V_JAMMED);  // knocked down / slipped
      break;
    case CLOSING:
      if ((uint32_t)(now - t0_) >= close_ms_) {
        if (up) {
          st_ = STUCK_UP;
          setReport(V_JAMMED);
        } else {
          st_ = CLOSED;
          setReport(V_CLOSED);
        }
      }
      break;
    case STUCK_UP:
      if (!up) {
        st_ = CLOSED;
        setReport(V_CLOSED);
      }
      break;
    case CLOSED:
      if (up) {  // lifted by hand: camera exposed, but we never asked
        st_ = STUCK_UP;
        setReport(V_JAMMED);
      }
      break;
  }
}

}  // namespace face
