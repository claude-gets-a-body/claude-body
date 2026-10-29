"""Export only some parts (one at a time, to keep memory low), assembly + print pose, and update parts.json.
    python export_some.py body_front body_back ...    (names from model.printed(); 'vendor' re-exports the vendor envelopes)"""
import gc, json, math, sys, time
sys.path.insert(0, "/home/nick/Desktop/Electrifix-Claude/claude-body/cad")
import trimesh
from build123d import export_stl
import model as M
import build as B

BUILDERS = {
    "body_floor": M.body_floor, "body_lid": M.body_lid, "screen_clamp": M.screen_clamp,
    "body_front": lambda: M.body_shells()[0], "body_back": lambda: M.body_shells()[1],
    "ball_bowl": M.ball_bowl, "ball_cap": M.ball_cap, "pan_gear": M.pan_gear, "pinion_gear": M.pinion_gear,
    "clutch_hub": M.clutch_hub, "clutch_cap": M.clutch_cap, "tilt_adapter": M.tilt_adapter, "tilt_coupler": M.tilt_coupler,
    "head_rear": lambda: M.head_shell()[0], "head_front": lambda: M.head_front(M.head_shell()[1]),
    "shutter": M.shutter, "head_frame": M.head_frame, "hub_drive": lambda: M.hubs()[0], "hub_idle": lambda: M.hubs()[1],
    "ear_L": lambda: M.ear("L"), "ear_R": lambda: M.ear("R"),
    "eye_backplate_L": lambda: M.eye_backplate("L"), "eye_backplate_R": lambda: M.eye_backplate("R"),
    "waist_deck": M.waist_deck,
}
rows = {r["part"]: r for r in json.load(open(B.OUT / "parts.json"))}
for name in sys.argv[1:]:
    t = time.time()
    if name == "vendor":
        for vn, shape in M.vendor().items():
            export_stl(shape, str(B.ASM / f"_v_{vn}.stl"), tolerance=0.2, angular_tolerance=0.3)
        print("vendor done", flush=True)
        continue
    shape = BUILDERS[name]()
    export_stl(shape, str(B.ASM / f"{name}.stl"), tolerance=0.05, angular_tolerance=0.15)
    del shape; gc.collect()
    m = trimesh.load(B.ASM / f"{name}.stl", force="mesh")
    R = trimesh.transformations.euler_matrix(*map(math.radians, B.ORIENT[name]), "sxyz")
    m.apply_transform(R)
    lo, hi = m.bounds
    m.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
    m.export(B.PRINT / f"{name}.stl")
    e = m.extents
    rows[name] = {"part": name, "x": round(e[0], 1), "y": round(e[1], 1), "z": round(e[2], 1),
                  "grams_pla": round(m.volume / 1000 * 1.24 * 0.45 + m.area / 100 * 0.06, 0),
                  "material": B.MAT.get(name, "PETG" if name.startswith(("chassis", "waist", "body_lid", "hub", "head_frame", "wheel", "caster", "dock", "body_floor", "screen")) else "PLA")}
    print(f"{name}: {e.round(1)} {time.time() - t:.0f}s watertight={m.is_watertight}", flush=True)
json.dump(list(rows.values()), open(B.OUT / "parts.json", "w"), indent=1)
