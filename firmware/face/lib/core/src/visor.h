#pragma once
// Visor state machine (PROTOCOL 2). Hardware-free.
//
// The only position sensor is the visor-UP switch, so:
//  * `open` is reported ONLY while the switch reads closed (visor up);
//  * commanded open and the switch hasn't closed within open_timeout_ms
//    -> `jammed`, and the visor is driven closed again;
//  * the switch opening while we are `open` (visor knocked/pushed down)
//    -> `jammed`, close;
//  * `closed` is reported close_ms after commanding close AND with the switch
//    open (not up). Switch still up after that -> `jammed` (stuck up), and it
//    keeps being driven closed until the switch releases;
//  * the switch closing while we never asked for open (someone lifted it by
//    hand) -> `jammed`, keep driving closed. Never reported as `open`.
//  * on boot it closes.
#include <stdint.h>

namespace face {

enum VisorReport : uint8_t { V_CLOSED = 0, V_MOVING, V_OPEN, V_JAMMED };
const char* visorName(VisorReport r);

class Visor {
 public:
  Visor(uint32_t open_timeout_ms, uint32_t close_ms) : open_to_(open_timeout_ms), close_ms_(close_ms) {}
  void boot(uint32_t now_ms);  // command close, report moving
  void command(bool open, uint32_t now_ms);
  // switch_up: debounced visor-up switch (true = closed = visor up).
  void update(bool switch_up, uint32_t now_ms);

  bool servoOpen() const { return servo_open_; }  // where to drive the servo
  VisorReport report() const { return report_; }
  // True once after the reported state changed (caller sends `visor`).
  bool takeChanged() {
    const bool c = changed_;
    changed_ = false;
    return c;
  }

 private:
  enum State : uint8_t { CLOSING, CLOSED, OPENING, OPEN, STUCK_UP };
  void setReport(VisorReport r);
  void startClose(uint32_t now, VisorReport r);
  uint32_t open_to_, close_ms_;
  State st_ = CLOSING;
  VisorReport report_ = V_MOVING;
  bool servo_open_ = false;
  bool changed_ = false;
  uint32_t t0_ = 0;
};

}  // namespace face
