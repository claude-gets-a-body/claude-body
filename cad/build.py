"""Build every part, export STLs (assembly pose + print pose), and run the fit/safety checks.

    ~/.venvs/cad/bin/python build.py            # export + checks
    ~/.venvs/cad/bin/python build.py --checks   # checks only (uses existing meshes)
"""
import itertools, json, math, sys, time
from pathlib import Path
import numpy as np
import trimesh
from build123d import export_stl
import model
import params as P

OUT = Path(__file__).parent / "out"
ASM = OUT / "assembly"
PRINT = OUT / "print"
for d in (ASM, PRINT):
    d.mkdir(parents=True, exist_ok=True)

# print orientation: rotation (deg about X, Y, Z) applied before dropping onto the bed
ORIENT = {
    "chassis_plate": (0, 0, 0), "bumper": (0, 0, 0), "skirt_rear": (0, 0, 0),
    "wheel_hub_L": (90, 0, 0), "wheel_hub_R": (-90, 0, 0), "tyre_L": (90, 0, 0), "tyre_R": (90, 0, 0),
    "caster_housing_F": (180, 0, 0), "caster_retainer_F": (0, 0, 0), "caster_housing_R": (180, 0, 0), "caster_retainer_R": (0, 0, 0), "eye_backplate_L": (0, -90, 0), "eye_backplate_R": (0, -90, 0), "waist_deck": (0, 0, 0), "body_floor": (0, 0, 0),
    "body_front": (0, 0, 0), "body_back": (0, 0, 0), "screen_clamp": (0, -72, 0),
    "body_lid": (180, 0, 0), "ball_bowl": (180, 0, 0), "ball_cap": (0, 0, 0),
    "pan_gear": (0, 0, 0), "pinion_gear": (0, 0, 0),
    "head_rear": (0, -90, 0), "head_front": (0, 90, 0), "shutter": (0, -90, 0),
    "clutch_hub": (0, 0, 0), "clutch_cap": (0, 0, 0), "tilt_adapter": (90, 0, 0), "tilt_coupler": (-90, 0, 0),
    "head_frame": (180, 0, 0), "hub_drive": (90, 0, 0), "hub_idle": (-90, 0, 0),
    "ear_L": (90, 0, 0), "ear_R": (-90, 0, 0),
    "dock_base": (0, 0, 0), "dock_tower_lower": (0, 90, 0), "dock_tower_upper": (0, 90, 0),
}
# filament + count, for the print list
MAT = {
    "tyre_L": "TPU 95A", "tyre_R": "TPU 95A", "ear_L": "TPU 95A (orange)", "ear_R": "TPU 95A (orange)",
    "head_front": "PETG charcoal", "shutter": "PLA orange",
    "pan_gear": "PETG", "pinion_gear": "PETG", "head_rear": "PLA cream", "body_front": "PLA cream",
    "body_back": "PLA cream", "bumper": "PETG cream", "skirt_rear": "PETG cream", "ball_cap": "PLA charcoal",
    "ball_bowl": "PETG charcoal", "clutch_hub": "PETG", "clutch_cap": "PETG", "tilt_adapter": "PETG", "tilt_coupler": "PETG",
}


def to_mesh(path):
    return trimesh.load(path, force="mesh")


def export_all():
    t = time.time()
    parts = model.printed()
    vend = model.vendor()
    for f in list(ASM.glob("*.stl")) + list(PRINT.glob("*.stl")):          # no stale meshes from renamed parts
        f.unlink()
    for name, shape in parts.items():
        export_stl(shape, str(ASM / f"{name}.stl"), tolerance=0.05, angular_tolerance=0.15)
    for name, shape in vend.items():
        export_stl(shape, str(ASM / f"_v_{name}.stl"), tolerance=0.2, angular_tolerance=0.3)
    # print pose
    rows = []
    for name in parts:
        m = to_mesh(ASM / f"{name}.stl")
        rx, ry, rz = ORIENT[name]
        R = trimesh.transformations.euler_matrix(*map(math.radians, (rx, ry, rz)), "sxyz")
        m.apply_transform(R)
        lo, hi = m.bounds
        m.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
        m.export(PRINT / f"{name}.stl")
        size = m.extents
        rows.append({"part": name, "x": round(size[0], 1), "y": round(size[1], 1), "z": round(size[2], 1),
                     "grams_pla": round(m.volume / 1000 * 1.24 * 0.45 + m.area / 100 * 0.06, 0),  # ~2 walls + 15% infill guess
                     "material": MAT.get(name, "PETG" if name.startswith(("chassis", "waist", "body_lid", "hub", "head_frame", "wheel", "caster", "dock", "body_floor")) else "PLA")})
    json.dump(rows, open(OUT / "parts.json", "w"), indent=1)
    print(f"exported {len(parts)} printed + {len(vend)} vendor meshes in {time.time() - t:.0f}s")


# ------------------------------------------------------------------ checks
results = []


def check(name, ok, detail):
    ok = bool(ok)
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")


def load_asm():
    meshes = {}
    for f in sorted(ASM.glob("*.stl")):
        meshes[f.stem] = to_mesh(f)
    return meshes


def bed_fit():
    lim = P.BED - 2 * P.BED_MARGIN
    for f in sorted(PRINT.glob("*.stl")):
        m = to_mesh(f)
        e = m.extents
        ok = e[0] <= lim and e[1] <= lim and e[2] <= P.BED - P.BED_MARGIN
        if not ok:
            check(f"bed fit {f.stem}", False, f"{e.round(1)} > {lim}")
    check("bed fit (all parts)", all(r[1] for r in results if r[0].startswith("bed fit ")), f"limit {lim} mm footprint")


def watertight(meshes):
    """Tessellation seams (a missing sliver at a sphere pole etc.) — the slicer auto-repairs these.
    Flag anything bigger than a seam."""
    from trimesh.grouping import group_rows
    worst = {}
    for n, m in meshes.items():
        if n.startswith("_v_"):
            continue
        e = m.edges_sorted
        worst[n] = len(group_rows(e, require_count=1))
    seams = {n: k for n, k in worst.items() if k}
    check("printed meshes closed (seam-level gaps only)", all(k <= 80 for k in worst.values()),
          ", ".join(f"{n}:{k} open edges" for n, k in seams.items()) or "all watertight")


INTENDED = {frozenset(("wheel_hub_L", "tyre_L")), frozenset(("wheel_hub_R", "tyre_R")),     # tyre is a stretch fit
            frozenset(("wheel_hub_L", "axle_pin_L")), frozenset(("wheel_hub_R", "axle_pin_R"))}  # pin is a press fit


def interference(shapes, tol=2.0):
    """Exact B-rep intersection volume for every pair whose boxes overlap."""
    names = list(shapes)
    boxes = {n: shapes[n].bounding_box() for n in names}
    hits = []
    for a, b in itertools.combinations(names, 2):
        ba, bb = boxes[a], boxes[b]
        if (ba.max.X <= bb.min.X or bb.max.X <= ba.min.X or ba.max.Y <= bb.min.Y or bb.max.Y <= ba.min.Y
                or ba.max.Z <= bb.min.Z or bb.max.Z <= ba.min.Z):
            continue
        try:
            v = (shapes[a] & shapes[b]).volume
        except Exception:
            v = float("nan")
        if not (v < tol) and frozenset((a, b)) not in INTENDED:
            hits.append((a, b, round(v, 1)))
    for a, b, v in hits:
        check(f"clash {a} x {b}", False, f"{v} mm^3 overlap")
    check("no clashes", not hits, f"{len(hits)} clashing pairs (tol {tol} mm^3)")
    return hits


def rot_about_tilt(m, deg):
    T = trimesh.transformations
    c = [0, 0, P.TILT_AXIS_Z]
    return m.copy().apply_transform(T.rotation_matrix(math.radians(deg), [0, 1, 0], c))


def rot_about_pan(m, deg):
    T = trimesh.transformations
    return m.copy().apply_transform(T.rotation_matrix(math.radians(deg), [0, 0, 1], [0, 0, 0]))


HEAD = ["_v_ear_servo_L", "_v_ear_servo_R", "head_rear", "head_front", "head_frame", "shutter", "ear_L", "ear_R", "eye_backplate_L", "eye_backplate_R", "_v_lcd_L", "_v_lcd_R",
        "_v_camera_uvc", "_v_xvf3800", "_v_tof_head"]
BODY_FIXED = ["body_lid", "body_front", "body_back"]


def head_clear_sphere(meshes, shapes):
    from build123d import Pos, Sphere
    c = np.array([0, 0, P.TILT_AXIS_Z])
    worst = 1e9
    who = ""
    sphere = Pos(0, 0, P.TILT_AXIS_Z) * Sphere(P.HEAD_CLEAR_R - 0.2)
    for n in HEAD:
        m = meshes[n]
        d = np.linalg.norm(m.vertices - c, axis=1).min()
        v = (shapes[n.replace("_v_", "")] & sphere).volume
        if d < worst:
            worst, who = d, n
        if v > 0.5:
            check(f"head part inside ball-clear sphere: {n}", False, f"{v:.1f} mm^3")
    check("head stays outside the ball-clearance sphere", worst >= P.HEAD_CLEAR_R - 0.3,
          f"closest {who} at {worst:.1f} mm (need >= {P.HEAD_CLEAR_R})")


def pinch_gaps(meshes):
    """Smallest gap between the moving head and the fixed body across the tilt/pan range.
    Rule: a moving gap must stay > 25 mm (finger can't be trapped) — or be constant (< 4 mm) by design."""
    head = trimesh.util.concatenate([meshes[n] for n in HEAD])
    body = trimesh.util.concatenate([meshes[n] for n in BODY_FIXED])
    pq = trimesh.proximity.ProximityQuery(body)
    worst = (1e9, None)
    # the head can be forced to the hard stops (limp on a fault, or a child pushing it), so sweep to them
    bowl = meshes["ball_bowl"]
    c_ = np.array([0, 0, P.TILT_AXIS_Z])
    bp = bowl.sample(20000)
    post_pts = bp[(np.linalg.norm(bp - c_, axis=1) > P.BALL_R + 1) & (bp[:, 2] < P.TILT_AXIS_Z - 40)]
    post_cloud = trimesh.PointCloud(post_pts)
    worst_post = (1e9, None)
    for tilt in np.linspace(P.TILT_STOP_MIN, P.TILT_STOP_MAX, 9):
        h = rot_about_tilt(head, -tilt)
        d = np.abs(trimesh.proximity.ProximityQuery(h).signed_distance(post_pts[::4])).min()
        if d < worst_post[0]:
            worst_post = (d, round(float(tilt), 1))
    check("head-to-neck-post gap at every tilt up to the hard stops", worst_post[0] > 25.0,
          f"min {worst_post[0]:.1f} mm at tilt {worst_post[1]}")
    for tilt in np.linspace(P.TILT_STOP_MIN, P.TILT_STOP_MAX, 9):
        for pan in (0, 60, 120, 150):
            h = rot_about_pan(rot_about_tilt(head, -tilt), pan)   # +tilt = looking up = front rises
            pts = h.sample(6000)
            d = np.abs(pq.signed_distance(pts)).min()
            if d < worst[0]:
                worst = (d, (round(tilt, 1), pan))
    check("head-to-body gap over full tilt/pan", worst[0] > 25.0, f"min {worst[0]:.1f} mm at tilt,pan={worst[1]}")
    # ball vs head constant gap
    ball = trimesh.util.concatenate([meshes["ball_bowl"], meshes["ball_cap"]])
    pqb = trimesh.proximity.ProximityQuery(ball)
    edge = meshes["head_rear"].vertices
    c = np.array([0, 0, P.TILT_AXIS_Z])
    near = edge[np.linalg.norm(edge - c, axis=1) < P.HEAD_CLEAR_R + 0.3]   # the head's edge ring on the clear sphere
    on_axis = np.hypot(near[:, 0], near[:, 2] - P.TILT_AXIS_Z) < P.HUB_D / 2 + 2       # hub passages: the hub fills that gap
    near = near[~on_axis]
    if len(near):
        gaps = np.abs(pqb.signed_distance(near))
        check("head-to-ball gap at the edge ring is 2.8-4 mm", gaps.min() > 2.8 and gaps.max() < 4.0, f"{gaps.min():.2f}..{gaps.max():.2f} mm over {len(near)} edge points")


def wheel_well(meshes):
    skirt = trimesh.util.concatenate([meshes["bumper"], meshes["skirt_rear"]])
    pq = trimesh.proximity.ProximityQuery(skirt)
    for s in "LR":
        t = meshes[f"tyre_{s}"]
        d = np.abs(pq.signed_distance(t.sample(4000))).min()
        check(f"tyre {s} to skirt clearance", d >= 3.0, f"{d:.1f} mm")


def gears():
    cd = math.dist((0, 0), (P.PAN_SERVO_X, 0))
    check("gear centre distance", abs(cd - P.GEAR_CD) < 0.01, f"{cd:.2f} vs {P.GEAR_CD}")


def moved(shape, dx=0.0, dy=0.0, dz=0.0):
    from build123d import Pos
    return Pos(dx, dy, dz) * shape


def clash_along(shapes, movers, obstacles, axis, dists, label, tol=2.0):
    """Slide `movers` (a set of part names that travel together) along `axis` by each distance and
    report the worst overlap with `obstacles`. This is the assembly path, not just the final pose."""
    worst = (0.0, None, None)
    for d in dists:
        off = {"x": (d, 0, 0), "y": (0, d, 0), "z": (0, 0, d)}[axis]
        for mv in movers:
            ms = moved(shapes[mv], *off)
            mb = ms.bounding_box()
            for ob in obstacles:
                obb = shapes[ob].bounding_box()
                if (mb.max.X <= obb.min.X or obb.max.X <= mb.min.X or mb.max.Y <= obb.min.Y or obb.max.Y <= mb.min.Y
                        or mb.max.Z <= obb.min.Z or obb.max.Z <= mb.min.Z):
                    continue
                v = (ms & shapes[ob]).volume
                if v > worst[0]:
                    worst = (v, f"{mv}~{ob}", d)
    check(label, worst[0] < tol, "clear all the way" if worst[0] < tol else f"{worst[1]} {worst[0]:.1f} mm^3 at {worst[2]} mm")


def assembly_paths(shapes):
    near = [0.5, 1, 2, 3, 5, 8, 12, 18, 25, 35, 50, 70, 90]
    on_frame = ["head_frame", "xvf3800", "ear_servo_L", "ear_servo_R"]
    ball = ["ball_bowl", "ball_cap", "tilt_adapter", "tilt_coupler", "servo_tilt"]
    hubs = ["hub_drive", "hub_idle"]
    # 1. the frame (with its servos and mic board) lowers over the ball before the hubs go in
    clash_along(shapes, on_frame, ball, "z", near, "assembly: frame lowers over the ball")
    # 2. hubs slide in sideways through the frame plates into the ball
    clash_along(shapes, ["hub_drive"], on_frame + ball, "y", near[:10], "assembly: drive hub slides in from +Y")
    clash_along(shapes, ["hub_idle"], on_frame + ball, "y", [-d for d in near[:10]], "assembly: idle hub slides in from -Y")
    # 3. the front half (carrying eyes, camera, shutter, head ToF) closes from the front
    front = ["head_front", "shutter", "eye_backplate_L", "eye_backplate_R", "lcd_L", "lcd_R", "camera_uvc", "tof_head"]
    clash_along(shapes, front, on_frame + ball + hubs, "x", near, "assembly: front half closes from +X")
    # 4. then the rear half from behind
    clash_along(shapes, ["head_rear"], on_frame + ball + hubs + front, "x", [-d for d in near], "assembly: rear half closes from -X")


def bumper_travel(shapes):
    others = [n for n in shapes if n not in ("bumper",) and not n.startswith("dock")]
    clash_along(shapes, ["bumper"], others, "x", [-1.0, -2.0, -P.BUMPER_TRAVEL], f"bumper moves back {P.BUMPER_TRAVEL} mm freely")


def drop_lead():
    stop = P.V_MAX ** 2 / (2 * P.ESTOP_DECEL) * 1000 + P.V_MAX * P.STOP_LATENCY_S * 1000
    for i, (r_, a) in enumerate(P.DROP_TOF_POS):
        x = r_ * math.cos(math.radians(a))
        lead = abs(x)                       # wheels are on x = 0; front sensors lead forward motion, rear lead reversing
        check(f"drop sensor {i} lead vs stopping distance", lead > stop + 10,
              f"{lead:.0f} mm ahead of the wheels vs {stop:.0f} mm to stop (1.5 m/s2 + {P.STOP_LATENCY_S * 1000:.0f} ms)")


def stability(meshes):
    # crude centre of mass: printed parts at 25% solid density 1.24, vendor parts at real-ish masses
    vend_mass = {"_v_ballast_low": 100, "_v_ballast_deck": 150, "_v_ear_servo_L": 13, "_v_ear_servo_R": 13, "_v_axle_pin_L": 12, "_v_axle_pin_R": 12, "_v_tof_head": 2, "_v_servo_wheel_L": 55, "_v_servo_wheel_R": 55, "_v_servo_pan": 55, "_v_servo_tilt": 55,
                 "_v_battery_3s2p": 320, "_v_lidar_stl19p": 45, "_v_pi5": 60, "_v_speaker_L": 150, "_v_speaker_R": 150, "_v_screen_7in": 250, "_v_m2_board": 40, "_v_coral": 25, "_v_fan_exhaust": 15,
                 "_v_xvf3800": 40, "_v_caster_ball_F": 67, "_v_caster_ball_R": 67, "_v_lcd_L": 8, "_v_lcd_R": 8, "_v_camera_uvc": 10}
    tot, mom = 0.0, np.zeros(3)
    for n, m in meshes.items():
        if n.startswith("dock"):
            continue
        if n.startswith("_v_"):
            g = vend_mass.get(n, 15)
        else:
            # walls print solid (3 perimeters ~1.2 mm on every surface), the rest at ~15 % infill
            solid = min(m.volume, m.area * 1.2)
            g = 1.24 * (solid + 0.15 * (m.volume - solid)) / 1000
        tot += g
        mom += g * m.center_mass
    com = mom / tot
    # support polygon: wheels at (0, +/-WHEEL_Y), rear ball at (-CASTER_X_REAR, 0); the front ball is lifted, so
    # forward tipping is about the wheel-to-front-ball lines once it touches
    wl, wr = np.array([0, P.WHEEL_Y]), np.array([0, -P.WHEEL_Y])
    rc, fc = np.array([-P.CASTER_X_REAR, 0]), np.array([P.CASTER_X_FRONT, 0])
    def edge_dist(p, a, b):
        ab = b - a
        d = p - a
        return abs(ab[0] * d[1] - ab[1] * d[0]) / np.linalg.norm(ab)
    cxy = com[:2]
    edges = {"wheel-rear ball (L)": (wl, rc), "wheel-rear ball (R)": (wr, rc), "wheel-front ball (L)": (wl, fc), "wheel-front ball (R)": (wr, fc)}
    tips = {k: math.degrees(math.atan2(edge_dist(cxy, a, b), com[2])) for k, (a, b) in edges.items()}
    worst = min(tips, key=tips.get)
    rear_share = -com[0] / P.CASTER_X_REAR
    rock = 9.81 * (-com[0]) / com[2]
    check("centre of mass behind the axle (rear caster loaded)", rear_share > 0.12,
          f"COM x={com[0]:.1f} y={com[1]:.1f} z={com[2]:.1f} mm, mass ~{tot / 1000:.2f} kg; rear ball carries ~{rear_share * 100:.0f} %; rocks forward only above {rock:.2f} m/s2 (a_max 0.5)")
    check("tip angle over the real support polygon > tilt cut-out (15 deg) + 5", tips[worst] > 20,
          f"min {tips[worst]:.0f} deg over {worst}; " + ", ".join(f"{k} {v:.0f}" for k, v in tips.items()))


PHASE = {  # 1 = head on a stand first, 2 = legs, 3 = home (dock)
    **{n: 1 for n in ("head_rear", "head_front", "clutch_hub", "clutch_cap", "tilt_adapter", "tilt_coupler", "head_frame", "shutter", "ear_L", "ear_R", "eye_backplate_L",
                      "eye_backplate_R", "hub_drive", "hub_idle", "ball_bowl", "ball_cap", "pan_gear", "pinion_gear",
                      "body_lid", "body_front", "body_back", "body_floor", "screen_clamp")},
    **{n: 3 for n in ("dock_base", "dock_tower_lower", "dock_tower_upper")},
}
NOTES = {
    "chassis_plate": "flat; standoffs and towers print upward, no supports",
    "bumper": "upright, no supports", "skirt_rear": "upright, no supports",
    "wheel_hub_L": "inner face down", "wheel_hub_R": "inner face down",
    "tyre_L": "TPU, slow (Elegoo TPU 95A @ECC profile), dry spool", "tyre_R": "TPU, slow, dry spool",
    "ear_L": "TPU, flat", "ear_R": "TPU, flat",
    "body_front": "upright; tree supports under the screen window's top edge and the clamp bosses", "body_back": "upright; tree supports under the note pocket",
    "body_lid": "top face down; hanger plates point up", "ball_bowl": "split face down, post up; tree supports inside the bowl",
    "ball_cap": "split face down", "head_rear": "back face down; tree supports (touching buildplate) under the top fillet",
    "head_front": "front face down, so the face is smooth; tree supports inside only", "head_frame": "bridge face down",
    "screen_clamp": "flat",
    "dock_tower_lower": "on its side", "dock_tower_upper": "tag face down",
}


def print_list():
    rows = json.load(open(OUT / "parts.json"))
    lines = ["# Print list", "", "Generated by `build.py` from the model; don't edit by hand. Files are in `cad/out/print/`, already",
             "laid flat in print orientation. Phase 1 = head on a stand (print first), 2 = legs, 3 = dock.",
             "Settings: 0.2 mm layers, 3 walls, 15 % gyroid unless noted, textured PEI, M3 heat-set inserts at 220 °C.",
             "", "| Phase | Part | Material | Size (mm) | ~g | How |", "|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (PHASE.get(r["part"], 2), r["part"])):
        n = r["part"]
        lines.append(f"| {PHASE.get(n, 2)} | `{n}` | {r['material']} | {r['x']:.0f} × {r['y']:.0f} × {r['z']:.0f} | "
                     f"{r['grams_pla']:.0f} | {NOTES.get(n, 'as exported')} |")
    lines += ["", f"Total ≈ {sum(r['grams_pla'] for r in rows) / 1000:.1f} kg. Component brackets for the camera, boards and "
              "buck converter are deliberately NOT in this list. They get modelled after the real parts are measured."]
    (Path(__file__).parent / "PRINT-LIST.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    if "--checks" not in sys.argv:
        export_all()
        print_list()
    meshes = load_asm()
    shapes = {**model.printed(), **model.vendor()}
    bed_fit()
    watertight(meshes)
    gears()
    wheel_well(meshes)
    head_clear_sphere(meshes, shapes)
    pinch_gaps(meshes)
    stability(meshes)
    drop_lead()
    interference(shapes)
    assembly_paths(shapes)
    bumper_travel(shapes)
    fails = [r for r in results if not r[1]]
    json.dump([{"check": n, "ok": o, "detail": d} for n, o, d in results], open(OUT / "checks.json", "w"), indent=1)
    print(f"\n{len(results) - len(fails)}/{len(results)} checks passed")
