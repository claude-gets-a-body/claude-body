#pragma once
// Eye geometry: where the iris disc sits and where the lid edges cut it.
// Hardware-free; the renderer just fills the regions this describes.
#include "moods.h"

namespace face {

struct EyeGeom {
  float cx, cy, r;       // iris disc on the 240x240 screen
  float top_f, bot_f;    // effective lid fractions (pose + blink)
  float tilt, smile;     // copied from the pose
  int inner_dir;         // screen-x direction of the nose side: -1 or +1
  bool closed;           // lids meet: draw the closed-eye line instead
  float meet_y;          // where the lids meet (screen y)
};

// side: 0 = robot's left eye, 1 = robot's right eye. Screens face outwards,
// so the robot's left is the viewer's right: gaze x = -1 (robot's left)
// moves the pupils towards screen +x. gaze y = +1 (up) is screen -y.
// blink: 0 open .. 1 closed. scale: tiny "breathing" size factor (~1.0).
EyeGeom eyeGeometry(const EyePose& p, float gaze_x, float gaze_y, float blink, int side,
                    float scale, int size_px, float max_dx, float max_dy);

// Lid edges at screen column x (screen y grows downwards).
// Everything above topLidY and below botLidY is lid (black).
float topLidY(const EyeGeom& g, float x);
float botLidY(const EyeGeom& g, float x);

}  // namespace face
