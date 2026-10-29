"""Light check of the head + neck only: build just those parts and test every pair for overlap.
The full build.py --checks builds the whole (now mostly obsolete) base too and runs out of memory."""
import itertools, sys
sys.path.insert(0, "/home/nick/Desktop/Electrifix-Claude/claude-body/cad")
import model, params as P
from build import INTENDED

print("building", flush=True)
rear, front = model.head_shell()
p = {
    "head_rear": rear, "head_front": model.head_front(front), "head_frame": model.head_frame(),
    "eye_backplate_L": model.eye_backplate("L"), "eye_backplate_R": model.eye_backplate("R"),
    "shutter": model.shutter(), "tilt_adapter": model.tilt_adapter(), "tilt_coupler": model.tilt_coupler(),
    "ball_bowl": model.ball_bowl(), "ball_cap": model.ball_cap(),
    "ear_L": model.ear("L"), "ear_R": model.ear("R"),
}
p["hub_drive"], p["hub_idle"] = model.hubs()
v = model.vendor()
keep = ["servo_tilt", "lcd_L", "lcd_R", "camera_uvc", "tof_head", "xvf3800", "ear_servo_L", "ear_servo_R"]
shapes = {**p, **{k: v[k] for k in keep}}
del v
print("built", len(shapes), flush=True)

bad = 0
for a, b in itertools.combinations(shapes, 2):
    ba, bb = shapes[a].bounding_box(), shapes[b].bounding_box()
    if (ba.max.X <= bb.min.X or bb.max.X <= ba.min.X or ba.max.Y <= bb.min.Y or bb.max.Y <= ba.min.Y
            or ba.max.Z <= bb.min.Z or bb.max.Z <= ba.min.Z):
        continue
    try:
        vol = (shapes[a] & shapes[b]).volume
    except Exception as e:
        vol = float("nan")
    if not (vol < 2.0) and frozenset((a, b)) not in INTENDED:
        bad += 1
        print(f"CLASH {a} x {b}: {vol:.1f} mm^3", flush=True)
print(f"pairwise: {bad} clashes", flush=True)

# the coupler must stay inside the ball's inner surface (it turns with the head inside the ball)
c = P.TILT_AXIS_Z
inner = model.Pos(0, 0, c) * model.Sphere(P.BALL_R - P.BALL_WALL)
out = (p["tilt_coupler"] - inner).volume
print(f"coupler outside the ball's inner sphere: {out:.2f} mm^3", flush=True)
bb = p["tilt_coupler"].bounding_box()
print(f"coupler Y {bb.min.Y:.1f}..{bb.max.Y:.1f}, hub_drive hex starts Y {p['hub_drive'].bounding_box().min.Y:.1f}", flush=True)
for n in ("eye_backplate_L", "eye_backplate_R", "tilt_coupler", "hub_drive", "head_front"):
    print(n, "volume", round(p[n].volume), "valid", p[n].is_valid(), flush=True)
