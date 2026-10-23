#pragma once
// Two GC9A01 round LCDs on one SPI bus: shared SCK/MOSI/DC/RST, separate CS.
//
// LovyanGFX drives ONE panel object with CS disabled (pin_cs = -1); this file
// toggles the two CS lines itself. Both panels get the init sequence together
// (both CS low), then each frame goes to one panel at a time.
//
// Frames: each eye has two 240x240 RGB565 sprites in PSRAM (double buffer).
// While the DMA sends one eye's finished frame, the CPU draws the other eye
// into its back buffer, so drawing overlaps the SPI transfer. step() is
// non-blocking: it never waits for the DMA, the main loop keeps running.
#include <Arduino.h>

#include "eye_geom.h"

class EyeDisplay {
 public:
  bool begin();  // false if the sprites could not be allocated in PSRAM
  // Set what the next frame should show. geom[0] = robot's left eye.
  void setFrame(const face::EyeGeom geom[2], bool asleep);
  // Advance the pipeline. Returns true when a full frame (both eyes) is out.
  bool step(uint32_t now_ms);
  bool idle() const { return stage_ == 0; }
  void setBacklight(float level);  // 0..1 (perceptual curve applied here)
  float fps() const { return fps_; }
  uint32_t renderUs() const { return render_us_; }
  bool psramOk() const { return psram_ok_; }

 private:
  void drawEye(int eye, int buf);
  void push(int eye, int buf);
  void selectPanel(int eye);  // -1 = none

  face::EyeGeom geom_[2];
  bool asleep_ = false;
  int stage_ = 0;
  int buf_ = 0;
  uint32_t frames_ = 0, fps_window_ms_ = 0;
  uint32_t render_us_ = 0;
  float fps_ = 0;
  bool psram_ok_ = false;
};
