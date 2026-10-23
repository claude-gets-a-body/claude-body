#pragma once
// Five VL53L1X on one I2C bus; addresses assigned at boot via XSHUT.
// Non-blocking: poll() checks one sensor per call and reads it if ready.
#include <Arduino.h>
#include <VL53L1X.h>
#include <Wire.h>

// Down sensors (CAD): front-left +27 deg (r 100 mm), REAR 145 deg (r 95 mm), front-right -27 deg (r 100 mm).
enum TofIndex { TOF_DOWN_L = 0, TOF_DOWN_REAR, TOF_DOWN_R, TOF_FWD_L, TOF_FWD_R, TOF_COUNT };

struct TofReading {
  bool alive = false;     // initialised OK
  uint16_t mm = 0;
  uint8_t status = 255;   // VL53L1X::RangeStatus, 255 = none yet
  uint32_t last_ms = 0;   // time of the last reading
  bool fresh(uint32_t now, uint32_t stale_ms) const {
    return alive && status != 255 && (uint32_t)(now - last_ms) < stale_ms;
  }
};

class TofArray {
 public:
  // Blocking (setup only): bring sensors out of reset one by one.
  int begin(TwoWire& wire);
  // Returns the index of a sensor that produced a new reading, or -1.
  int poll(uint32_t now_ms);
  // Try to bring back sensors that failed (blocking up to ~60 ms each);
  // only call while the wheels are stopped.
  void retryDead(uint32_t now_ms);
  const TofReading& operator[](int i) const { return r_[i]; }
  uint8_t aliveMask() const;

 private:
  bool initOne(int i);
  VL53L1X s_[TOF_COUNT];
  TofReading r_[TOF_COUNT];
  int next_ = 0;
  uint32_t last_check_ms_[TOF_COUNT] = {};
  uint32_t last_retry_ms_ = 0;
  TwoWire* wire_ = nullptr;
};
