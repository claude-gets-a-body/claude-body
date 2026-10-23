"""Blender renders of the assembly.  blender -b -P render.py -- <view> [<view> ...]
Views: hero, side, back, exploded, head, dock."""
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

HERE = Path(__file__).parent
ASM = HERE / "out" / "assembly"
OUTDIR = HERE.parent / "renders"
OUTDIR.mkdir(exist_ok=True)
sys.path.insert(0, str(HERE))
import params as P  # noqa: E402

TILT_C = Vector((0, 0, P.TILT_AXIS_Z))


def srgb(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c] + [1.0]


COL = {
    "cream": srgb("#EFE7D8"), "charcoal": srgb("#2A2A2C"), "orange": srgb("#D97757"),
    "tpu": srgb("#3A3A3A"), "petg": srgb("#E9E3D6"), "natural": srgb("#F4F1EA"),
    "servo": srgb("#1D1F24"), "pcb": srgb("#1F5E3A"), "metal": srgb("#B8BCC2"), "battery": srgb("#2F6FB5"),
    "lidar": srgb("#141414"), "board": srgb("#203A6B"),
}
PART_COL = {
    "bumper": "cream", "skirt_rear": "cream", "body_front": "cream", "body_back": "cream", "head_rear": "cream",
    "head_front": "charcoal", "ball_bowl": "charcoal", "ball_cap": "charcoal", "shutter": "orange",
    "ear_L": "orange", "ear_R": "orange", "tyre_L": "tpu", "tyre_R": "tpu", "chest_grille": "natural",
    "body_lid": "charcoal", "waist_deck": "charcoal", "chassis_plate": "petg", "dock_base": "charcoal",
    "dock_tower_lower": "charcoal", "dock_tower_upper": "charcoal", "pan_gear": "orange", "pinion_gear": "orange", "clutch_hub": "orange", "clutch_cap": "orange", "tilt_adapter": "orange",
}
VEND_COL = {"servo": "servo", "battery": "battery", "lidar": "lidar", "pi5": "pcb", "bearing": "metal",
            "caster_ball": "metal", "xvf": "board", "tof": "board", "camera": "board", "speaker": "servo"}

HEAD = {"head_rear", "head_front", "head_frame", "shutter", "ear_L", "ear_R", "eye_backplate_L", "eye_backplate_R",
        "hub_drive", "hub_idle", "_v_lcd_L", "_v_lcd_R", "_v_camera_uvc", "_v_xvf3800", "_v_tof_head"}
PAN = HEAD | {"ball_bowl", "ball_cap", "pan_gear", "_v_servo_tilt", "tilt_adapter"}
DOCK = {"dock_base", "dock_tower_lower", "dock_tower_upper"}


def material(name, rgba, emit=None, strength=0.0, rough=0.55, transmission=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = rgba
    b.inputs["Roughness"].default_value = rough
    if transmission:
        b.inputs["Transmission Weight"].default_value = transmission
    if emit:
        b.inputs["Emission Color"].default_value = emit
        b.inputs["Emission Strength"].default_value = strength
    return m


def eye_material():
    """Procedural round eye: orange iris, dark pupil-ish centre, a highlight. Emissive."""
    m = bpy.data.materials.new("eye")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    # object coords: local Y/Z of the LCD disc relative to its centre
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    length = nt.nodes.new("ShaderNodeVectorMath")
    length.operation = "LENGTH"
    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(sep.outputs["Y"], comb.inputs["X"])
    nt.links.new(sep.outputs["Z"], comb.inputs["Y"])
    nt.links.new(comb.outputs[0], length.inputs[0])
    scale = nt.nodes.new("ShaderNodeMath")
    scale.operation = "DIVIDE"
    scale.inputs[1].default_value = P.LCD_PCB_D / 2
    nt.links.new(length.outputs["Value"], scale.inputs[0])
    nt.links.new(scale.outputs[0], ramp.inputs["Fac"])
    cr = ramp.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.0, (1.0, 0.55, 0.30, 1)
    cr.elements[1].position, cr.elements[1].color = 0.62, (0.85, 0.30, 0.12, 1)
    e = cr.elements.new(0.70)
    e.color = (0.02, 0.02, 0.02, 1)
    nt.links.new(ramp.outputs["Color"], em.inputs["Color"])
    em.inputs["Strength"].default_value = 4.0
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


def import_part(path):
    bpy.ops.wm.stl_import(filepath=str(path))
    ob = bpy.context.selected_objects[0]
    ob.name = path.stem
    # parts are in mm; scene in metres
    ob.scale = (0.001, 0.001, 0.001)
    return ob


def set_origin_world_mm(ob, c):
    pass


def rotate_about(ob, axis, deg, centre_mm):
    c = Vector(centre_mm) * 0.001
    R = Matrix.Rotation(math.radians(deg), 4, axis)
    T = Matrix.Translation(c) @ R @ Matrix.Translation(-c)
    ob.matrix_world = T @ ob.matrix_world


def build_scene(pose_tilt=0.0, pose_pan=0.0, exploded=False, with_dock=False, show_vendor=True):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = int(__import__("os").environ.get("SAMPLES", "96"))
    sc.cycles.use_denoising = True
    sc.render.resolution_x = int(__import__("os").environ.get("RES", "1400"))
    sc.render.resolution_y = int(__import__("os").environ.get("RES", "1400"))
    sc.view_settings.view_transform = "AgX"
    world = bpy.data.worlds.new("w")
    sc.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.92, 0.92, 0.94, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.7

    mats = {k: material(k, v, rough=0.45 if k in ("cream", "petg") else 0.55) for k, v in COL.items()}
    mats["natural"] = material("natural_diffuser", COL["natural"], emit=(1.0, 0.62, 0.35, 1), strength=0.6, rough=0.4)
    eye = eye_material()
    led = material("led", COL["orange"], emit=(1.0, 0.5, 0.25, 1), strength=6.0)

    objs = {}
    for f in sorted(ASM.glob("*.stl")):
        n = f.stem
        if n in DOCK and not with_dock:
            continue
        if n.startswith("_v_") and not show_vendor and n not in ("_v_lcd_L", "_v_lcd_R"):
            continue
        ob = import_part(f)
        if n.startswith("_v_lcd"):
            ob.data.materials.append(eye)
            # object coords centred on the disc
            bpy.context.view_layer.objects.active = ob
            bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
        elif n == "_v_led_ring_16":
            ob.data.materials.append(led)
        elif n.startswith("_v_"):
            key = next((v for k, v in VEND_COL.items() if k in n), "servo")
            ob.data.materials.append(mats[key])
        else:
            ob.data.materials.append(mats[PART_COL.get(n, "petg")])
        bpy.ops.object.shade_auto_smooth() if hasattr(bpy.ops.object, "shade_auto_smooth") else None
        objs[n] = ob

    for n, ob in objs.items():
        if n in HEAD and pose_tilt:
            rotate_about(ob, "Y", -pose_tilt, (0, 0, P.TILT_AXIS_Z))
        if n in PAN and pose_pan:
            rotate_about(ob, "Z", pose_pan, (0, 0, 0))

    if exploded:
        groups = [
            ({"chassis_plate", "caster_housing_F", "caster_housing_R", "caster_retainer_F", "caster_retainer_R",
              "_v_battery_3s2p", "_v_servo_wheel_L", "_v_servo_wheel_R", "_v_caster_ball_F", "_v_caster_ball_R",
              "_v_bearing_608_L", "_v_bearing_608_R", "_v_axle_pin_L", "_v_axle_pin_R", "_v_tof_drop_0", "_v_tof_drop_1", "_v_tof_drop_2",
              "_v_tof_fwd_0", "_v_tof_fwd_1"}, 0),
            ({"wheel_hub_L", "tyre_L"}, (0, 70, 0)), ({"wheel_hub_R", "tyre_R"}, (0, -70, 0)),
            ({"bumper"}, (60, 0, 0)), ({"skirt_rear"}, (-60, 0, 0)),
            ({"waist_deck", "_v_lidar_stl19p"}, (0, 0, 70)),
            ({"body_floor", "_v_pi5"}, (0, 0, 130)),
            ({"body_front", "chest_grille", "_v_speaker_40", "_v_led_ring_16"}, (70, 0, 160)),
            ({"body_back"}, (-70, 0, 160)),
            ({"body_lid", "pinion_gear", "clutch_hub", "clutch_cap", "_v_servo_pan", "_v_pan_bearing_6806"}, (0, 0, 220)),
            ({"pan_gear"}, (0, 0, 200)),
            ({"ball_bowl", "_v_servo_tilt", "tilt_adapter"}, (0, 0, 260)), ({"ball_cap"}, (0, 0, 300)),
            ({"head_frame", "hub_drive", "hub_idle", "_v_xvf3800", "ear_L", "ear_R"}, (0, 0, 360)),
            ({"head_rear"}, (-80, 0, 380)),
            ({"head_front", "shutter", "eye_backplate_L", "eye_backplate_R", "_v_lcd_L", "_v_lcd_R", "_v_camera_uvc", "_v_tof_head"}, (90, 0, 380)),
        ]
        for names, off in groups:
            if not off:
                continue
            for n in names:
                if n in objs:
                    objs[n].location = objs[n].location + Vector(off) * 0.001

    # floor
    bpy.ops.mesh.primitive_plane_add(size=6, location=(0, 0, 0))
    floor = bpy.context.object
    floor.data.materials.append(material("floor", srgb("#D9D4CC"), rough=0.8))
    # lights
    bpy.ops.object.light_add(type="AREA", location=(0.9, -0.7, 1.3))
    key = bpy.context.object
    key.data.energy = 260
    key.data.size = 1.2
    key.rotation_euler = (math.radians(45), 0, math.radians(50))
    bpy.ops.object.light_add(type="AREA", location=(-0.8, 0.9, 0.9))
    fill = bpy.context.object
    fill.data.energy = 90
    fill.data.size = 1.5
    fill.rotation_euler = (math.radians(55), 0, math.radians(-140))
    return objs


def camera(loc, target, lens=55):
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.object
    d = Vector(target) - Vector(loc)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens
    bpy.context.scene.camera = cam


def render(name):
    bpy.context.scene.render.filepath = str(OUTDIR / f"{name}.png")
    bpy.ops.render.render(write_still=True)
    print("wrote", OUTDIR / f"{name}.png")


VIEWS = {
    "hero": dict(scene=dict(pose_tilt=12, pose_pan=18, show_vendor=False), cam=((0.95, -0.62, 0.42), (0, 0, 0.22), 60)),
    "side": dict(scene=dict(show_vendor=False), cam=((0.02, -1.3, 0.24), (0, 0, 0.22), 60)),
    "back": dict(scene=dict(show_vendor=False), cam=((-0.95, 0.55, 0.45), (0, 0, 0.22), 60)),
    "head": dict(scene=dict(pose_tilt=8, show_vendor=False), cam=((0.55, -0.22, 0.42), (0.02, 0, 0.355), 85)),
    "exploded": dict(scene=dict(exploded=True, show_vendor=True), cam=((1.25, -1.0, 0.75), (0, 0, 0.37), 50)),
    "inside": dict(scene=dict(exploded=True, show_vendor=True), cam=((0.0, -1.55, 0.40), (0, 0, 0.37), 45)),
    "dock": dict(scene=dict(with_dock=True, pose_pan=150, show_vendor=False), cam=((0.55, -1.1, 0.55), (-0.08, 0, 0.18), 50)),
}

if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else list(VIEWS)
    for v in args:
        cfg = VIEWS[v]
        build_scene(**cfg["scene"])
        loc, tgt, lens = cfg["cam"]
        camera(loc, tgt, lens)
        render(v)
