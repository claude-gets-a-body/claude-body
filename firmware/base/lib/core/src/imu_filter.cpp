#include "imu_filter.h"

#include <math.h>

namespace imu {

static const float kRad2Deg = 57.2957795f;

void rotate(const int R[3][3], const float in[3], float out[3]) {
  for (int r = 0; r < 3; r++) out[r] = R[r][0] * in[0] + R[r][1] * in[1] + R[r][2] * in[2];
}

static float wrap180(float a) {
  while (a > 180.0f) a -= 360.0f;
  while (a <= -180.0f) a += 360.0f;
  return a;
}

void anglesFromUp(const float up[3], float& roll, float& pitch) {
  roll = atan2f(up[1], up[2]) * kRad2Deg;
  pitch = atan2f(-up[0], sqrtf(up[1] * up[1] + up[2] * up[2])) * kRad2Deg;
}

void orientationFromQuat(const float q[4], const int R[3][3], float& roll, float& pitch,
                         float& yaw) {
  const float w = q[0], x = q[1], y = q[2], z = q[3];
  // sensor -> world rotation matrix
  const float S[3][3] = {
      {1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)},
      {2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)},
      {2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)}};
  // robot -> world = S * R^T  (R is orthonormal: sensor = R^T * robot)
  float M[3][3];
  for (int i = 0; i < 3; i++)
    for (int j = 0; j < 3; j++)
      M[i][j] = S[i][0] * R[j][0] + S[i][1] * R[j][1] + S[i][2] * R[j][2];
  const float up[3] = {M[2][0], M[2][1], M[2][2]};  // world z in robot axes
  anglesFromUp(up, roll, pitch);
  yaw = atan2f(M[1][0], M[0][0]) * kRad2Deg;
}

void Complementary::update(const float a[3], const float g[3], float dt) {
  float acc_roll, acc_pitch;
  anglesFromUp(a, acc_roll, acc_pitch);
  const float mag = sqrtf(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
  gz = g[2];
  if (!seeded_) {
    roll = acc_roll;
    pitch = acc_pitch;
    seeded_ = true;
  } else {
    const float gr = roll + g[0] * dt;
    const float gp = pitch + g[1] * dt;
    // Trust the accelerometer only when it reads close to 1 g (not during a
    // knock or while being lifted/swung).
    if (mag > 0.6f && mag < 1.4f) {
      // blend on the shortest arc so +179 / -179 do not average to 0
      roll = wrap180(gr + (1.0f - alpha_) * wrap180(acc_roll - gr));
      pitch = gp + (1.0f - alpha_) * (acc_pitch - gp);
    } else {
      roll = wrap180(gr);
      pitch = gp;
    }
  }
  yaw = wrap180(yaw + g[2] * dt);
}

}  // namespace imu
