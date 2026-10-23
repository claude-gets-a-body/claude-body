#pragma once
// Complementary filter for roll/pitch from accel + gyro, yaw from gyro only.
// Hardware-free. Robot axes: x forward, y left, z up. Angles in degrees.
#include <stdint.h>

namespace imu {

// out = R * in (3x3 integer rotation for the board's mounting).
void rotate(const int R[3][3], const float in[3], float out[3]);

// Roll/pitch (deg) from the "up" direction expressed in robot axes
// (at rest an accelerometer reads +1 g along up).
void anglesFromUp(const float up[3], float& roll, float& pitch);

// Fused orientation (BNO085 game rotation vector, quaternion w,x,y,z rotating
// sensor axes into the world frame) -> robot roll/pitch/yaw in degrees.
// R is the mounting matrix (robot = R * sensor), as for rotate().
void orientationFromQuat(const float q[4], const int R[3][3], float& roll, float& pitch,
                         float& yaw);

class Complementary {
 public:
  explicit Complementary(float alpha) : alpha_(alpha) {}
  // a: accel in g (robot axes), g: gyro in deg/s (robot axes, bias removed).
  void update(const float a[3], const float g[3], float dt);
  void reset() { seeded_ = false; roll = pitch = yaw = 0; }
  float roll = 0, pitch = 0, yaw = 0, gz = 0;  // yaw wrapped to (-180, 180]

 private:
  float alpha_;
  bool seeded_ = false;
};

// Running mean for the boot-time gyro bias.
class BiasEstimator {
 public:
  void add(const float g[3]) {
    for (int i = 0; i < 3; i++) sum_[i] += g[i];
    n_++;
  }
  int count() const { return n_; }
  void bias(float out[3]) const {
    for (int i = 0; i < 3; i++) out[i] = n_ ? (float)(sum_[i] / n_) : 0;
  }

 private:
  double sum_[3] = {0, 0, 0};
  int n_ = 0;
};

}  // namespace imu
