#pragma once
// IMU interface. One implementation is compiled in:
//   default        BNO085 (on-chip fusion; game rotation vector + calibrated gyro)
//   -DIMU_MPU6050  MPU-6050 (raw registers + complementary filter in imu_filter.cpp)
// Robot axes (REP-103): x forward, y left, z up. +roll = left side up,
// +pitch = nose down, +yaw = turning left. Degrees.
#include <Arduino.h>
#include <Wire.h>

class Imu {
 public:
  bool begin(TwoWire& wire);
  // Call often; it rate-limits itself. Returns true when a new sample arrived.
  bool poll(uint32_t now_ms);
  // Initialised, warmed up and producing fresh data.
  bool ok(uint32_t now_ms) const;
  bool ready() const { return ready_; }  // finished boot (bias / first fusion sample)
  bool failed() const { return failed_; }
  const char* name() const;
  float roll = 0, pitch = 0, yaw = 0, gz = 0;

 private:
  bool ready_ = false, failed_ = false;
  uint32_t last_sample_ms_ = 0, last_poll_ms_ = 0, last_retry_ms_ = 0;
  TwoWire* wire_ = nullptr;
};
