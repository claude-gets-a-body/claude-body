#pragma once
// PROTOCOL 2 (Pi <-> face): line parsing and message formatting. Hardware-free.
//
// Beyond PROTOCOL.md (ignorable by the Pi):
//   Pi -> face  {"t":"ping","id":..}  -> {"t":"pong","id":..}
//   Pi -> face  {"t":"diag"}          -> {"t":"diag","fps":..,...}
//   A `visor` command that changes nothing re-sends the current `visor`
//   state, so the Pi can always resync.
//   face -> Pi  {"t":"range","head_mm":N} at 10 Hz is in PROTOCOL 2.
#include <stddef.h>
#include <stdint.h>

#include "moods.h"

namespace face {

enum class Type : uint8_t { Invalid, Unknown, Mood, Gaze, Blink, Ears, Visor, Bright, Ping, Diag };

struct Command {
  Type type = Type::Invalid;
  Mood mood = NEUTRAL;
  bool has_ms = false;
  uint32_t ms = 0;
  float x = 0, y = 0;                 // gaze, clamped -1..1
  bool has_l = false, has_r = false;  // ears
  float l = 0, r = 0;
  bool wiggle = false;
  bool open = false;                  // visor
  float b = 0;                        // bright, clamped 0..1
  char id_json[48] = "null";
};

Type parse(const char* line, Command& out);

size_t fmtVisor(char* b, size_t n, const char* state);
size_t fmtTouch(char* b, size_t n, const char* g);
size_t fmtHello(char* b, size_t n, const char* fw);
size_t fmtPong(char* b, size_t n, const char* id_json);
size_t fmtRange(char* b, size_t n, int head_mm);

// Head range sensor value for `range.head_mm` (VL53L1X range_status codes):
//   valid / sigma-fail     -> the distance (clamped to 0..RANGE_CLEAR_MM)
//   min-range clipped      -> 0 (something right in front)
//   signal fail / out of bounds / wrap / crosstalk -> RANGE_CLEAR_MM (4000, clear)
//   dead, stale, hardware fail, anything else      -> -1 (the body treats it as slow)
int headRangeValue(bool alive, bool fresh, uint8_t status, int mm);

}  // namespace face
