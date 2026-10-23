// BNO085 implementation of Imu (default). Adafruit BNO08x library over I2C.
// Note: the BNO08x uses I2C clock stretching; the ESP32-S3 I2C controller
// handles it, but if the bus proves flaky on the real harness, the BNO085's
// UART-RVC mode is the fallback (see README).
#ifndef IMU_MPU6050

#include <Adafruit_BNO08x.h>

#include "config.h"
#include "imu.h"
#include "imu_filter.h"

static Adafruit_BNO08x bno(-1);
static const int kMount[3][3] = IMU_R;
static float q_[4] = {1, 0, 0, 0};

static bool enableReports() {
  return bno.enableReport(SH2_GAME_ROTATION_VECTOR, BNO085_REPORT_US) &&
         bno.enableReport(SH2_GYROSCOPE_CALIBRATED, BNO085_REPORT_US);
}

const char* Imu::name() const { return "bno085"; }

bool Imu::begin(TwoWire& wire) {
  wire_ = &wire;
  if (!bno.begin_I2C(BNO085_I2C_ADDR, &wire) || !enableReports()) {
    failed_ = true;
    return false;
  }
  failed_ = false;
  return true;
}

bool Imu::poll(uint32_t now) {
  if (failed_) {
    // retry every 5 s (the sensor may have been unplugged / browned out)
    if ((uint32_t)(now - last_retry_ms_) > 5000) {
      last_retry_ms_ = now;
      begin(*wire_);
    }
    return false;
  }
  if ((uint32_t)(now - last_poll_ms_) < 2) return false;
  last_poll_ms_ = now;
  if (bno.wasReset()) enableReports();
  bool got_q = false;
  sh2_SensorValue_t v;
  for (int i = 0; i < 4 && bno.getSensorEvent(&v); i++) {  // bounded per call
    if (v.sensorId == SH2_GAME_ROTATION_VECTOR) {
      q_[0] = v.un.gameRotationVector.real;
      q_[1] = v.un.gameRotationVector.i;
      q_[2] = v.un.gameRotationVector.j;
      q_[3] = v.un.gameRotationVector.k;
      got_q = true;
    } else if (v.sensorId == SH2_GYROSCOPE_CALIBRATED) {
      const float g[3] = {v.un.gyroscope.x * 57.2957795f, v.un.gyroscope.y * 57.2957795f,
                          v.un.gyroscope.z * 57.2957795f};
      float gr[3];
      imu::rotate(kMount, g, gr);
      gz = gr[2];
    }
  }
  if (got_q) {
    imu::orientationFromQuat(q_, kMount, roll, pitch, yaw);
    last_sample_ms_ = now;
    ready_ = true;
  }
  return got_q;
}

bool Imu::ok(uint32_t now) const {
  return ready_ && !failed_ && (uint32_t)(now - last_sample_ms_) < IMU_STALE_MS;
}

#endif  // !IMU_MPU6050
