#pragma once
// PROTOCOL 1 (Pi <-> base): line parsing and message formatting.
// Hardware-free: ArduinoJson for parsing, snprintf for output (fixed number
// formats keep the 50 Hz lines short and never print "nan").
//
// Messages beyond PROTOCOL.md (all ignorable by the Pi, per the
// "unknown types are ignored" rule):
//   Pi -> base  {"t":"cal"}    re-run floor calibration of the down ToFs
//                              (robot must be still, on flat floor)
//   Pi -> base  {"t":"diag"}   ask for a diagnostics line
//   base -> Pi  {"t":"cal","floor_mm":[l,c,r],"ok":[bool,bool,bool]}
//
// Drop sensor order everywhere (`drop`, `floor_mm`, `ok`) is [l, c, r] as in
// PROTOCOL.md, but c is the REAR sensor: [front-left +27 deg, REAR 145 deg,
// front-right -27 deg]. Drop events are `drop_l`, `drop_rear`, `drop_r`.
//   base -> Pi  {"t":"limits","v_max":..,"a_max":..,"w_max":..}  reply to `limits`
//   base -> Pi  {"t":"diag", ...}
//   `fault` may also be "servo_error" (a wheel servo stopped answering).
#include <stddef.h>
#include <stdint.h>

#include "led_anim.h"

namespace proto {

enum class Type : uint8_t {
  Invalid,  // not JSON / missing "t" / bad fields -> ignored
  Unknown,  // valid JSON, unknown "t" -> ignored
  Vel,
  Head,
  Light,
  Stop,
  Torque,
  Limits,
  Ping,
  Cal,
  Diag,
};

struct Command {
  Type type = Type::Invalid;
  // vel
  float v = 0, w = 0;
  bool has_seq = false;
  int32_t seq = 0;
  // head
  bool has_pan = false, has_tilt = false, has_speed = false;
  float pan = 0, tilt = 0, speed = 0;
  // light
  led::Mode mode = led::OFF;
  bool has_rgb = false;
  uint8_t rgb[3] = {0, 0, 0};
  // torque
  bool on = false;
  // limits (NAN = not given)
  float v_max = 0, a_max = 0, w_max = 0;
  // ping: the id value re-serialised as JSON (number, string, ...)
  char id_json[48] = "null";
};

Type parse(const char* line, Command& out);

struct StateMsg {
  float bat_v = 0;
  int bat_pct = 0;
  bool charging = false, on_dock = false;
  bool pack_ok = false;
  float pack_c = 0;
  bool bump[2] = {false, false};
  bool drop[3] = {false, false, false};  // [front-left, REAR, front-right]
  int fwd_mm[2] = {-1, -1};
  bool pan_ok = false, tilt_ok = false;
  float pan = 0, tilt = 0;
  bool motors = false;
  const char* fault = nullptr;
};

// All formatters write one line ending in '\n' and return its length, or 0 if
// it did not fit (the caller then drops the message).
size_t fmtOdom(char* b, size_t n, float x, float y, float th, float v, float w, uint32_t ts);
size_t fmtImu(char* b, size_t n, float roll, float pitch, float yaw, float gz);
size_t fmtState(char* b, size_t n, const StateMsg& s);
size_t fmtEvent(char* b, size_t n, const char* e, const char* detail);
size_t fmtHello(char* b, size_t n, const char* fw, float v_max, float a_max, float w_max);
size_t fmtPong(char* b, size_t n, const char* id_json);
size_t fmtCal(char* b, size_t n, const int floor_mm[3], const bool ok[3]);
size_t fmtLimits(char* b, size_t n, float v_max, float a_max, float w_max);

// JSON-escape src into dst (always NUL-terminated).
void jsonEscape(const char* src, char* dst, size_t n);

}  // namespace proto
