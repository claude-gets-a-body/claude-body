#pragma once
// Head-height forward VL53L1X (PROTOCOL 2 `range`). Non-blocking polling;
// a dead sensor reports -1 and is re-initialised now and then.
#include <Arduino.h>

class HeadRange {
 public:
  bool begin();                 // blocking (setup only, ~60 ms max)
  void poll(uint32_t now_ms);   // call every loop pass
  int value(uint32_t now_ms) const;  // what `range.head_mm` should say
  bool alive() const { return alive_; }

 private:
  bool init();
  bool alive_ = false;
  uint8_t status_ = 255;
  int mm_ = 0;
  uint32_t last_ms_ = 0, last_check_ms_ = 0, last_retry_ms_ = 0;
};
