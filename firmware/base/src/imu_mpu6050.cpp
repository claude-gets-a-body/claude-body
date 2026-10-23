// MPU-6050 implementation of Imu (build with -DIMU_MPU6050, env base_mpu6050).
// Raw register access; fusion in imu_filter.cpp (complementary filter).
#ifdef IMU_MPU6050

#include "config.h"
#include "imu.h"
#include "imu_filter.h"

static const uint8_t kAddr = 0x68;
static const int kMount[3][3] = IMU_R;
static imu::Complementary filt(IMU_COMP_ALPHA);
static imu::BiasEstimator bias_est;
static float bias_[3] = {0, 0, 0};

static bool wr(TwoWire& w, uint8_t reg, uint8_t v) {
  w.beginTransmission(kAddr);
  w.write(reg);
  w.write(v);
  return w.endTransmission() == 0;
}

const char* Imu::name() const { return "mpu6050"; }

bool Imu::begin(TwoWire& wire) {
  wire_ = &wire;
  wire.beginTransmission(kAddr);
  wire.write(0x75);  // WHO_AM_I
  bool ok = wire.endTransmission(false) == 0 && wire.requestFrom(kAddr, (uint8_t)1) == 1 &&
            (wire.read() & 0x7E) == 0x68;
  ok = ok && wr(wire, 0x6B, 0x01);  // wake, PLL on gyro X
  ok = ok && wr(wire, 0x1A, 0x03);  // DLPF ~44 Hz
  ok = ok && wr(wire, 0x1B, 0x08);  // gyro +-500 dps  (65.5 LSB per deg/s)
  ok = ok && wr(wire, 0x1C, 0x08);  // accel +-4 g      (8192 LSB per g)
  failed_ = !ok;
  return ok;
}

bool Imu::poll(uint32_t now) {
  if (failed_) {
    if ((uint32_t)(now - last_retry_ms_) > 5000) {
      last_retry_ms_ = now;
      begin(*wire_);
    }
    return false;
  }
  if ((uint32_t)(now - last_poll_ms_) < IMU_PERIOD_MS) return false;
  const float dt = last_poll_ms_ ? (now - last_poll_ms_) / 1000.0f : IMU_PERIOD_MS / 1000.0f;
  last_poll_ms_ = now;
  wire_->beginTransmission(kAddr);
  wire_->write(0x3B);
  if (wire_->endTransmission(false) != 0 || wire_->requestFrom(kAddr, (uint8_t)14) != 14) {
    return false;  // goes stale -> ok() false -> tilt latch (fail-safe)
  }
  int16_t raw[7];
  for (int i = 0; i < 7; i++) {
    const int hi = wire_->read(), lo = wire_->read();
    raw[i] = (int16_t)((hi << 8) | lo);
  }
  const float a_s[3] = {raw[0] / 8192.0f, raw[1] / 8192.0f, raw[2] / 8192.0f};
  const float g_s[3] = {raw[4] / 65.5f, raw[5] / 65.5f, raw[6] / 65.5f};
  float a[3], g[3];
  imu::rotate(kMount, a_s, a);
  imu::rotate(kMount, g_s, g);
  if (!ready_) {  // boot: average the gyro bias while the robot is still
    bias_est.add(g);
    if (bias_est.count() >= IMU_BIAS_SAMPLES) {
      bias_est.bias(bias_);
      ready_ = true;
    }
    return false;
  }
  for (int i = 0; i < 3; i++) g[i] -= bias_[i];
  filt.update(a, g, dt);
  roll = filt.roll;
  pitch = filt.pitch;
  yaw = filt.yaw;
  gz = filt.gz;
  last_sample_ms_ = now;
  return true;
}

bool Imu::ok(uint32_t now) const {
  return ready_ && !failed_ && (uint32_t)(now - last_sample_ms_) < IMU_STALE_MS;
}

#endif  // IMU_MPU6050
