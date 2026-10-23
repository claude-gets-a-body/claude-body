#include "led_anim.h"

#include <math.h>
#include <string.h>

namespace led {

static const char* const kNames[MODE_COUNT] = {"off",   "idle",  "listen", "think",
                                               "speak", "alert", "sleep",  "charge"};

bool modeFromName(const char* name, Mode& out) {
  if (!name) return false;
  for (int i = 0; i < MODE_COUNT; i++) {
    if (strcmp(name, kNames[i]) == 0) {
      out = (Mode)i;
      return true;
    }
  }
  return false;
}

const char* modeName(Mode m) { return m < MODE_COUNT ? kNames[m] : "off"; }

Rgb defaultColour(Mode m) {
  switch (m) {
    case ALERT:
      return {255, 40, 20};
    case CHARGE:
      return {60, 220, 90};
    case LISTEN:
      return {255, 150, 110};  // lighter, whiter orange: "I'm listening"
    case SLEEP:
      return {217, 90, 60};
    default:
      return {0xD9, 0x77, 0x57};  // Claude orange
  }
}

static const float kTwoPi = 6.2831853f;

static Rgb scale(Rgb c, float k, uint8_t cap) {
  if (k < 0) k = 0;
  if (k > 1) k = 1;
  const float m = k * (float)cap / 255.0f;
  Rgb o;
  o.r = (uint8_t)lroundf(c.r * m);
  o.g = (uint8_t)lroundf(c.g * m);
  o.b = (uint8_t)lroundf(c.b * m);
  return o;
}

// 0..1 smooth breathing wave with the given period
static float breathe(uint32_t t, uint32_t period_ms) {
  const float ph = (float)(t % period_ms) / (float)period_ms;
  return 0.5f - 0.5f * cosf(kTwoPi * ph);
}

void render(Mode m, Rgb c, uint32_t t, int bat_pct, uint8_t cap, Rgb* out, int n) {
  if (n <= 0) return;
  switch (m) {
    case OFF:
      for (int i = 0; i < n; i++) out[i] = {0, 0, 0};
      break;

    case IDLE: {  // slow, soft breathing
      const float k = 0.10f + 0.25f * breathe(t, 4000);
      for (int i = 0; i < n; i++) out[i] = scale(c, k, cap);
      break;
    }

    case LISTEN:  // steady and bright
      for (int i = 0; i < n; i++) out[i] = scale(c, 0.70f, cap);
      break;

    case THINK: {  // a soft comet running round the ring, 1.2 s per lap
      const float head = (float)(t % 1200) / 1200.0f * n;
      for (int i = 0; i < n; i++) {
        float d = head - (float)i;  // distance behind the head
        while (d < 0) d += n;
        const float k = 0.08f + 0.85f * expf(-d * 0.9f);
        out[i] = scale(c, k, cap);
      }
      break;
    }

    case SPEAK: {  // lively flicker: two incommensurate waves, like speech
      const float s = (float)t / 1000.0f;
      const float k =
          0.45f + 0.25f * sinf(kTwoPi * 5.3f * s) * 0.5f + 0.25f * sinf(kTwoPi * 2.1f * s);
      for (int i = 0; i < n; i++) out[i] = scale(c, k, cap);
      break;
    }

    case ALERT: {  // 2 Hz on/off, full brightness
      const bool on = (t % 500) < 250;
      for (int i = 0; i < n; i++) out[i] = on ? scale(c, 1.0f, cap) : Rgb{0, 0, 0};
      break;
    }

    case SLEEP: {  // very dim, very slow
      const float k = 0.02f + 0.08f * breathe(t, 8000);
      for (int i = 0; i < n; i++) out[i] = scale(c, k, cap);
      break;
    }

    case CHARGE: {  // ring filled to battery %, with a slow shimmer on the top LED
      if (bat_pct < 0) bat_pct = 0;
      if (bat_pct > 100) bat_pct = 100;
      const int full = (int)floorf((float)bat_pct / 100.0f * n);
      for (int i = 0; i < n; i++) {
        if (i < full) out[i] = scale(c, 0.45f, cap);
        else if (i == full) out[i] = scale(c, 0.10f + 0.50f * breathe(t, 2000), cap);
        else out[i] = scale(c, 0.03f, cap);
      }
      break;
    }

    default:
      for (int i = 0; i < n; i++) out[i] = {0, 0, 0};
  }
}

}  // namespace led
