#include "eye_geom.h"

#include <math.h>

namespace face {

static float clampf(float x, float lo, float hi) { return x < lo ? lo : (x > hi ? hi : x); }

static const float kMeet = 0.62f;  // lids meet a bit below the middle, like real eyes

EyeGeom eyeGeometry(const EyePose& p, float gaze_x, float gaze_y, float blink, int side,
                    float scale, int size_px, float max_dx, float max_dy) {
  EyeGeom g;
  const float half = size_px * 0.5f;
  g.r = p.iris_r * scale;
  const float gx = clampf(gaze_x + p.gaze_x, -1, 1);
  const float gy = clampf(gaze_y + p.gaze_y, -1, 1);
  float dx = -gx * max_dx;  // robot's left = screen +x
  float dy = -gy * max_dy;  // up = screen -y
  // keep the disc inside the round glass
  const float room = half - 2 - g.r;
  const float d = sqrtf(dx * dx + dy * dy);
  if (room > 0 && d > room) {
    dx *= room / d;
    dy *= room / d;
  } else if (room <= 0) {
    dx = dy = 0;
  }
  g.cx = half + dx;
  g.cy = half + dy;
  blink = clampf(blink, 0, 1);
  float top = clampf(p.lid_top, 0, 1), bot = clampf(p.lid_bot, 0, 1);
  if (top < kMeet) top += (kMeet - top) * blink;
  if (bot < 1 - kMeet) bot += ((1 - kMeet) - bot) * blink;
  g.top_f = top;
  g.bot_f = bot;
  g.tilt = clampf(p.lid_tilt, -1, 1);
  g.smile = clampf(p.smile, 0, 1);
  g.inner_dir = side == 0 ? -1 : +1;
  g.closed = (top + bot) >= 0.97f;
  const float h = 2 * g.r;
  const float top_y = g.cy - g.r + top * h;
  const float bot_y = g.cy + g.r - bot * h;
  g.meet_y = g.closed ? (top_y + bot_y) * 0.5f : top_y;
  return g;
}

float topLidY(const EyeGeom& g, float x) {
  const float u = (x - g.cx) / g.r;  // -1..1 across the disc
  float y = g.cy - g.r + g.top_f * 2 * g.r;
  // gentle arch (edges a little lower) only once the lid is in the frame
  if (g.top_f > 0.01f) y += 0.12f * g.r * u * u;
  // tilt: + lowers the nose-side corner
  y += g.tilt * 0.38f * g.r * (u * g.inner_dir);
  return y;
}

float botLidY(const EyeGeom& g, float x) {
  const float u = (x - g.cx) / g.r;
  float y = g.cy + g.r - g.bot_f * 2 * g.r;
  if (g.bot_f > 0.01f) y -= 0.10f * g.r * u * u;
  // smile: the lower lid bulges up in the middle -> "^" crescent eye
  const float uu = u < -1 ? -1 : (u > 1 ? 1 : u);
  y -= g.smile * 0.95f * g.r * (1 - uu * uu);
  return y;
}

}  // namespace face
