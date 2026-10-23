#include "eyes.h"

#define LGFX_USE_V1
#include <LovyanGFX.hpp>

#include "config.h"
#include "pins.h"

// ---- LovyanGFX device: one GC9A01 panel object, CS handled by us ----------------
class LGFX_Eyes : public lgfx::LGFX_Device {
  lgfx::Panel_GC9A01 panel_;
  lgfx::Bus_SPI bus_;

 public:
  LGFX_Eyes() {
    auto b = bus_.config();
    b.spi_host = SPI2_HOST;
    b.spi_mode = 0;
    b.freq_write = LCD_SPI_HZ;
    b.freq_read = 16000000;
    b.spi_3wire = true;  // no MISO
    b.use_lock = true;
    b.dma_channel = SPI_DMA_CH_AUTO;
    b.pin_sclk = PIN_LCD_SCLK;
    b.pin_mosi = PIN_LCD_MOSI;
    b.pin_miso = -1;
    b.pin_dc = PIN_LCD_DC;
    bus_.config(b);
    panel_.setBus(&bus_);

    auto p = panel_.config();
    p.pin_cs = -1;  // two panels: CS is switched by EyeDisplay::selectPanel
    p.pin_rst = PIN_LCD_RST;
    p.pin_busy = -1;
    p.panel_width = EYE_SIZE;
    p.panel_height = EYE_SIZE;
    p.offset_x = 0;
    p.offset_y = 0;
    p.offset_rotation = 0;
    p.readable = false;
    p.invert = LCD_INVERT != 0;
    p.rgb_order = false;
    p.dlen_16bit = false;
    p.bus_shared = false;
    panel_.config(p);
    setPanel(&panel_);
  }
};

static LGFX_Eyes lcd;
static LGFX_Sprite spr[2][2] = {{LGFX_Sprite(&lcd), LGFX_Sprite(&lcd)},
                                {LGFX_Sprite(&lcd), LGFX_Sprite(&lcd)}};
static const int kCs[2] = {PIN_LCD_CS_LEFT, PIN_LCD_CS_RIGHT};

// Colours (RGB888 as uint32_t -> LovyanGFX converts)
static const uint32_t kIris = EYE_COLOUR, kRim = EYE_RIM_COLOUR, kGlint = EYE_HIGHLIGHT;

void EyeDisplay::selectPanel(int eye) {
  digitalWrite(kCs[0], eye == 0 ? LOW : HIGH);
  digitalWrite(kCs[1], eye == 1 ? LOW : HIGH);
}

bool EyeDisplay::begin() {
  pinMode(kCs[0], OUTPUT);
  pinMode(kCs[1], OUTPUT);
  // init both panels at once: identical controllers, shared DC/RST
  digitalWrite(kCs[0], LOW);
  digitalWrite(kCs[1], LOW);
  lcd.init();
  lcd.setRotation(LCD_ROTATION);
  lcd.fillScreen(TFT_BLACK);
  lcd.waitDisplay();
  selectPanel(-1);

  ledcAttach(PIN_LCD_BL, BL_PWM_HZ, BL_PWM_BITS);
  setBacklight(0);

  psram_ok_ = true;
  for (int e = 0; e < 2; e++)
    for (int b = 0; b < 2; b++) {
      spr[e][b].setColorDepth(16);
      spr[e][b].setPsram(true);
      if (!spr[e][b].createSprite(EYE_SIZE, EYE_SIZE)) psram_ok_ = false;
      else spr[e][b].fillScreen(TFT_BLACK);
    }
  // Keep the SPI transaction open for good: we are the bus's only user, and
  // it lets pushImageDMA run in the background between loop() passes.
  lcd.startWrite();
  return psram_ok_;
}

void EyeDisplay::setBacklight(float level) {
  if (level < 0) level = 0;
  if (level > 1) level = 1;
  const uint32_t maxd = (1UL << BL_PWM_BITS) - 1;
  ledcWrite(PIN_LCD_BL, (uint32_t)(level * level * maxd));  // perceptual-ish
}

void EyeDisplay::setFrame(const face::EyeGeom geom[2], bool asleep) {
  geom_[0] = geom[0];
  geom_[1] = geom[1];
  asleep_ = asleep;
}

// Darken an RGB565 pixel towards black by k (0..1) -- lid edge anti-aliasing.
static uint16_t darken565(uint16_t c, float k) {
  const float m = 1.0f - k;
  const uint16_t r = (uint16_t)(((c >> 11) & 0x1F) * m);
  const uint16_t g = (uint16_t)(((c >> 5) & 0x3F) * m);
  const uint16_t b = (uint16_t)((c & 0x1F) * m);
  return (uint16_t)((r << 11) | (g << 5) | b);
}

void EyeDisplay::drawEye(int eye, int buf) {
  LGFX_Sprite& s = spr[eye][buf];
  const face::EyeGeom& g = geom_[eye];
  s.fillScreen(TFT_BLACK);

  if (g.closed) {
    // A closed eye is a soft orange line, not nothing: reads as "resting",
    // not "switched off". Asleep sags into a content little "u" curve.
    const float half = g.r * 0.78f;
    const float sag = asleep_ ? 0.16f * g.r : 0.04f * g.r;
    const int N = 14;
    float px = g.cx - half, py = g.meet_y;
    for (int i = 1; i <= N; i++) {
      const float u = -1.0f + 2.0f * i / N;
      const float x = g.cx + u * half;
      const float y = g.meet_y + sag * (1 - u * u);
      s.drawWideLine(px, py, x, y, 3.2f, kIris);
      px = x;
      py = y;
    }
    return;
  }

  // Iris: darker rim + body, both anti-aliased.
  s.fillSmoothCircle(g.cx, g.cy, g.r, kRim);
  s.fillSmoothCircle(g.cx, g.cy, g.r - 6, kIris);
  // Highlights move a little less than the eye (they belong to the room light).
  const float hx = -(g.cx - EYE_SIZE / 2) * 0.25f, hy = -(g.cy - EYE_SIZE / 2) * 0.25f;
  s.fillSmoothCircle(g.cx - 0.36f * g.r + hx, g.cy - 0.40f * g.r + hy, 0.20f * g.r, kGlint);
  s.fillSmoothCircle(g.cx + 0.34f * g.r + hx, g.cy + 0.30f * g.r + hy, 0.08f * g.r, kGlint);

  // Lids: everything above the top edge / below the bottom edge goes black,
  // one column at a time, with the edge pixel blended for a smooth line.
  const int x0 = (int)floorf(g.cx - g.r - 1), x1 = (int)ceilf(g.cx + g.r + 1);
  const int top_of_disc = (int)floorf(g.cy - g.r - 1), bot_of_disc = (int)ceilf(g.cy + g.r + 1);
  for (int x = x0 < 0 ? 0 : x0; x <= x1 && x < EYE_SIZE; x++) {
    const float yt = face::topLidY(g, x + 0.5f);
    if (yt > top_of_disc) {
      const int yi = (int)floorf(yt);
      const int len = yi - top_of_disc;
      if (len > 0) s.fillRect(x, top_of_disc, 1, len, TFT_BLACK);
      if (yi >= 0 && yi < EYE_SIZE) s.drawPixel(x, yi, darken565(s.readPixel(x, yi), yt - yi));
    }
    const float yb = face::botLidY(g, x + 0.5f);
    if (yb < bot_of_disc) {
      const int yi = (int)ceilf(yb);
      const int len = bot_of_disc - yi + 1;
      if (len > 0) s.fillRect(x, yi, 1, len, TFT_BLACK);
      const int ye = yi - 1;
      if (ye >= 0 && ye < EYE_SIZE) s.drawPixel(x, ye, darken565(s.readPixel(x, ye), yi - yb));
    }
  }
}

void EyeDisplay::push(int eye, int buf) {
  selectPanel(eye);
  lcd.pushImageDMA(0, 0, EYE_SIZE, EYE_SIZE, (const lgfx::swap565_t*)spr[eye][buf].getBuffer());
}

bool EyeDisplay::step(uint32_t now) {
  if (!psram_ok_) return false;  // no frame buffers: stay dark rather than crash
  switch (stage_) {
    case 0: {  // draw left (the right eye's previous frame may still be in flight)
      const uint32_t t0 = micros();
      drawEye(0, buf_);
      render_us_ = micros() - t0;
      stage_ = 1;
      return false;
    }
    case 1:  // send left when the bus is free
      if (lcd.dmaBusy()) return false;
      push(0, buf_);
      stage_ = 2;
      return false;
    case 2: {  // draw right while the left goes out
      const uint32_t t0 = micros();
      drawEye(1, buf_);
      render_us_ += micros() - t0;
      stage_ = 3;
      return false;
    }
    case 3:
      if (lcd.dmaBusy()) return false;
      push(1, buf_);
      stage_ = 0;
      buf_ ^= 1;  // next frame draws into the other pair of sprites
      frames_++;
      if ((uint32_t)(now - fps_window_ms_) >= 1000) {
        fps_ = frames_ * 1000.0f / (float)(uint32_t)(now - fps_window_ms_);
        frames_ = 0;
        fps_window_ms_ = now;
      }
      return true;
  }
  return false;
}
