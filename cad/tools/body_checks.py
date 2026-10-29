"""Light checks for the abdomen: pairwise B-rep overlaps among the body + its bought parts, then the
head-to-body pinch-gap sweep on meshes (from build.py)."""
import itertools, sys
sys.path.insert(0, "/home/nick/Desktop/Electrifix-Claude/claude-body/cad")
import model as MD, params as P
import build as B

front, back = MD.body_shells()
shapes = {"body_front": front, "body_back": back, "body_floor": MD.body_floor(), "body_lid": MD.body_lid(),
          "screen_clamp": MD.screen_clamp(), "pan_gear": MD.pan_gear(), "pinion_gear": MD.pinion_gear(),
          "clutch_hub": MD.clutch_hub(), "clutch_cap": MD.clutch_cap(), "ball_bowl": MD.ball_bowl()}
v = MD.vendor()
for k in ("screen_7in", "pi5", "m2_board", "coral", "speaker_L", "speaker_R", "fan_exhaust", "servo_pan", "pan_bearing_6806"):
    shapes["_v_" + k] = v[k]
del v
print("built", flush=True)
bad = 0
for a, b in itertools.combinations(shapes, 2):
    ba, bb = shapes[a].bounding_box(), shapes[b].bounding_box()
    if (ba.max.X <= bb.min.X or bb.max.X <= ba.min.X or ba.max.Y <= bb.min.Y or bb.max.Y <= ba.min.Y
            or ba.max.Z <= bb.min.Z or bb.max.Z <= ba.min.Z):
        continue
    try:
        vol = (shapes[a] & shapes[b]).volume
    except Exception:
        vol = float("nan")
    if not (vol < 2.0):
        bad += 1
        print(f"CLASH {a} x {b}: {vol:.1f} mm^3", flush=True)
print(f"pairwise: {bad} clashes", flush=True)
del shapes
# head-to-body gap: sampled points + a KD-tree (the mesh proximity query blew the memory on the grilles)
import numpy as np, trimesh
from scipy.spatial import cKDTree
meshes = {n: trimesh.load(B.ASM / f"{n}.stl", force="mesh") for n in B.HEAD + B.BODY_FIXED}
body_pts = np.vstack([meshes[n].sample(60000) for n in B.BODY_FIXED])
tree = cKDTree(body_pts)
head = trimesh.util.concatenate([meshes[n] for n in B.HEAD])
hp = head.sample(20000)
worst = (1e9, None)
for tilt in np.linspace(P.TILT_STOP_MIN, P.TILT_STOP_MAX, 9):
    for pan in (0, 60, 120, 150):
        h = B.rot_about_pan(B.rot_about_tilt(trimesh.PointCloud(hp.copy()), -tilt), pan)
        d = tree.query(np.asarray(h.vertices))[0].min()
        if d < worst[0]:
            worst = (d, (round(float(tilt), 1), pan))
print(f"head-to-body gap over full tilt/pan: min {worst[0]:.1f} mm at tilt,pan={worst[1]} (need > 25)", flush=True)
import json
rows = {r["part"]: r for r in json.load(open(B.OUT / "parts.json"))}
lim = P.BED - 2 * P.BED_MARGIN
for n in ("body_front", "body_back", "body_floor", "body_lid", "screen_clamp"):
    r = rows[n]
    print(n, r["x"], r["y"], r["z"], "fits" if max(r["x"], r["y"]) <= lim and r["z"] <= P.BED - P.BED_MARGIN else "TOO BIG", flush=True)
