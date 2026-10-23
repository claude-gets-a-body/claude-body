#pragma once
// Chest ring animations (PROTOCOL 1 `light`). Hardware-free: renders RGB
// values for a given time; the main loop pushes them to the WS2812s.
#include <stdint.h>

namespace led {

enum Mode : uint8_t { OFF = 0, IDLE, LISTEN, THINK, SPEAK, ALERT, SLEEP, CHARGE, MODE_COUNT };

// "idle" -> IDLE etc. Returns false for unknown names.
bool modeFromName(const char* name, Mode& out);
const char* modeName(Mode m);

struct Rgb {
  uint8_t r, g, b;
};

// Default colour per mode when the Pi gives no `rgb`.
Rgb defaultColour(Mode m);

// Render one frame. `colour` is the mode colour (from `rgb` or the default),
// `bat_pct` drives the CHARGE fill, `max_brightness` 0..255 caps everything.
void render(Mode m, Rgb colour, uint32_t t_ms, int bat_pct, uint8_t max_brightness, Rgb* out,
            int n);

}  // namespace led
