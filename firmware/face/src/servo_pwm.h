#pragma once
// Hobby-servo PWM on the ESP32 LEDC peripheral (Arduino-ESP32 3.x API),
// with an optional linear ramp so the visor and ears move gently.
#include <Arduino.h>

#include "config.h"

class ServoPwm {
 public:
  bool attach(int pin, int initial_us) {
    pin_ = pin;
    cur_us_ = target_us_ = from_us_ = (float)initial_us;
    if (!ledcAttach(pin, SERVO_PWM_HZ, SERVO_PWM_BITS)) return false;
    write((float)initial_us);
    return true;
  }
  // Move to `us` over `ramp_ms` (0 = jump).
  void moveTo(int us, uint32_t ramp_ms, uint32_t now_ms) {
    if ((float)us == target_us_) return;
    from_us_ = cur_us_;
    target_us_ = (float)us;
    t0_ = now_ms;
    ramp_ms_ = ramp_ms;
  }
  void update(uint32_t now_ms) {
    float us = target_us_;
    if (ramp_ms_ > 0) {
      const float t = (float)(uint32_t)(now_ms - t0_) / (float)ramp_ms_;
      if (t < 1) us = from_us_ + (target_us_ - from_us_) * t;
    }
    if (fabsf(us - cur_us_) >= 1.0f) write(us);
  }
  // Direct, unramped set (ears are already slew-limited upstream).
  void set(float us) {
    target_us_ = from_us_ = us;
    ramp_ms_ = 0;
    if (fabsf(us - cur_us_) >= 1.0f) write(us);
  }

 private:
  void write(float us) {
    cur_us_ = us;
    const uint32_t period_us = 1000000UL / SERVO_PWM_HZ;
    const uint32_t duty = (uint32_t)(us * (float)((1UL << SERVO_PWM_BITS) - 1) / period_us);
    ledcWrite(pin_, duty);
  }
  int pin_ = -1;
  float cur_us_ = 1500, target_us_ = 1500, from_us_ = 1500;
  uint32_t t0_ = 0, ramp_ms_ = 0;
};
