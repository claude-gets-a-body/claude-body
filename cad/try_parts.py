import time, traceback, sys
import model
names = sys.argv[1:]
fns = {
 "chassis_plate": model.chassis_plate, "skirt": model.skirt_shells, "hub": lambda: model.wheel_hub("L"),
 "hubR": lambda: model.wheel_hub("R"), "tyre": lambda: model.tyre("L"), "caster": lambda: model.caster_parts(True), "eyebp": lambda: model.eye_backplate("L"),
 "deck": model.waist_deck, "floor": model.body_floor, "body": model.body_shells, "grille": model.chest_grille,
 "lid": model.body_lid, "bowl": model.ball_bowl, "cap": model.ball_cap, "gear": model.pan_gear,
 "pinion": model.pinion_gear, "clutch": model.clutch_hub, "cap2": model.clutch_cap, "adapter": model.tilt_adapter, "head": model.head_shell, "frame": model.head_frame, "hubs": model.hubs,
 "ear": lambda: model.ear("L"), "dock": model.dock, "vendor": model.vendor, "shutter": model.shutter,
}
for n in (names or fns):
    t = time.time()
    try:
        r = fns[n]()
        rs = r if isinstance(r, tuple) else (r,)
        info = []
        for x in rs:
            if isinstance(x, dict):
                info.append(f"{len(x)} items"); continue
            bb = x.bounding_box()
            info.append(f"vol={x.volume:.0f} bb=({bb.size.X:.0f},{bb.size.Y:.0f},{bb.size.Z:.0f}) solids={len(x.solids())} valid={x.is_valid}")
        print(f"OK  {n:14s} {time.time()-t:5.1f}s  " + " | ".join(info), flush=True)
    except Exception as e:
        print(f"ERR {n:14s} {time.time()-t:5.1f}s  {type(e).__name__}: {e}", flush=True)
        traceback.print_exc(limit=3)
