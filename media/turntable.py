"""Turntable video of the assembly, for the media kit.

    blender -b -P media/turntable.py                 # full render -> media/frames/, then encode
    TT_FRAMES=1,400 blender -b -P media/turntable.py # just those frames (test stills)
    TT_ENCODE_ONLY=1 blender -b -P media/turntable.py

Reuses cad/render.py's build_scene(), so the robot, colours and lights match the stills in renders/.
Timeline (30 fps):
    frames   1-360  camera orbits 360 deg around the robot (12 s, linear, so it loops cleanly)
    frames 361-420  camera holds; the head pans and tilts to look at the camera (2 s)
The shutter stays closed the whole time: nothing is being looked at, so the honest-eyes rule holds.
"""
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

MEDIA = Path(__file__).resolve().parent
ROOT = MEDIA.parent
sys.path.insert(0, str(ROOT / "cad"))
import render as R  # noqa: E402  (cad/render.py: build_scene, PAN, HEAD, camera helpers)
import params as P  # noqa: E402

FPS = 30
ORBIT_FRAMES = 360          # 12 s
HOLD_FRAMES = 60            # 2 s head turn
LAST = ORBIT_FRAMES + HOLD_FRAMES
RES = 1080
SAMPLES = int(os.environ.get("TT_SAMPLES", "20"))
FRAMES_DIR = MEDIA / "frames"

CAM_RADIUS = 1.13           # same distance as the hero still
CAM_Z = 0.42
CAM_AZ0 = -30.0             # start (and end) at a front-right three-quarter view; the face points +X
TARGET = (0.0, 0.0, 0.215)
LENS = 60
HEAD_PAN_END = CAM_AZ0      # face the camera
HEAD_TILT_END = 6.0         # a small look up (camera is just above eye height)


def setup():
    objs = R.build_scene(show_vendor=False)
    sc = bpy.context.scene
    sc.render.resolution_x = sc.render.resolution_y = RES
    sc.render.resolution_percentage = 100
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = 1, LAST
    sc.cycles.samples = SAMPLES
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.max_bounces = 4
    sc.cycles.use_denoising = True
    sc.render.use_persistent_data = True     # keep the BVH between frames
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    try:
        sc.view_settings.look = "AgX - Punchy"
    except TypeError:
        pass
    sc.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.55

    # Head rig: pan about Z through the origin, tilt about Y through the tilt axis (as in render.py).
    pan = bpy.data.objects.new("pan_rig", None)
    tilt = bpy.data.objects.new("tilt_rig", None)
    sc.collection.objects.link(pan)
    sc.collection.objects.link(tilt)
    tilt.location = (0, 0, P.TILT_AXIS_Z * 0.001)
    tilt.parent = pan
    bpy.context.view_layer.update()
    for n, ob in objs.items():
        if n in R.HEAD:
            parent = tilt
        elif n in R.PAN:
            parent = pan
        else:
            continue
        mw = ob.matrix_world.copy()
        ob.parent = parent
        ob.matrix_parent_inverse = parent.matrix_world.inverted()
        ob.matrix_world = mw

    def key(ob, frame, z=None, y=None):
        if z is not None:
            ob.rotation_euler.z = math.radians(z)
            ob.keyframe_insert("rotation_euler", index=2, frame=frame)
        if y is not None:
            ob.rotation_euler.y = math.radians(y)
            ob.keyframe_insert("rotation_euler", index=1, frame=frame)

    hold_start = ORBIT_FRAMES + 8           # a short beat before the head moves
    key(pan, 1, z=0)
    key(pan, hold_start, z=0)
    key(pan, LAST - 10, z=HEAD_PAN_END)
    key(tilt, 1, y=0)
    key(tilt, hold_start + 6, y=0)
    key(tilt, LAST - 6, y=-HEAD_TILT_END)   # render.py: rotate by -tilt about Y, positive = face up

    # Camera on an orbit empty, aimed with a track-to at the robot's middle.
    target = bpy.data.objects.new("cam_target", None)
    target.location = TARGET
    sc.collection.objects.link(target)
    orbit = bpy.data.objects.new("orbit", None)
    sc.collection.objects.link(orbit)
    a = math.radians(CAM_AZ0)
    bpy.ops.object.camera_add(location=(CAM_RADIUS * math.cos(a), CAM_RADIUS * math.sin(a), CAM_Z))
    cam = bpy.context.object
    cam.data.lens = LENS
    cam.parent = orbit
    tc = cam.constraints.new("TRACK_TO")
    tc.target = target
    tc.track_axis = "TRACK_NEGATIVE_Z"
    tc.up_axis = "UP_Y"
    sc.camera = cam
    orbit.rotation_euler.z = 0
    orbit.keyframe_insert("rotation_euler", index=2, frame=1)
    orbit.rotation_euler.z = 2 * math.pi
    orbit.keyframe_insert("rotation_euler", index=2, frame=ORBIT_FRAMES + 1)

    # Interpolation: orbit linear (clean loop), head moves eased.
    def fcurves(ob):
        ad = ob.animation_data
        if ad is None or ad.action is None:
            return []
        act = ad.action
        if hasattr(act, "fcurves") and len(getattr(act, "fcurves", [])):
            return list(act.fcurves)
        out = []  # Blender 5 layered actions
        for layer in getattr(act, "layers", []):
            for strip in layer.strips:
                for bag in strip.channelbags:
                    out.extend(bag.fcurves)
        return out

    for fc in fcurves(orbit):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
    for ob in (pan, tilt):
        for fc in fcurves(ob):
            for kp in fc.keyframe_points:
                kp.interpolation = "BEZIER"
                kp.easing = "AUTO"
    return sc


def render_frames(sc, frames):
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    for i, f in enumerate(frames):
        out = FRAMES_DIR / f"f{f:04d}.png"
        if out.exists() and not os.environ.get("TT_FORCE"):
            continue
        sc.frame_set(f)
        sc.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        el = time.time() - t0
        print(f"[turntable] frame {f} done, {i + 1}/{len(frames)}, {el:.0f}s elapsed", flush=True)
    return time.time() - t0


def encode():
    ff = shutil.which("ffmpeg")
    if not ff:
        print("[turntable] ffmpeg not found; frames are in", FRAMES_DIR)
        return
    mp4 = MEDIA / "claude-body-turntable.mp4"
    gif = MEDIA / "claude-body-turntable.gif"
    pat = str(FRAMES_DIR / "f%04d.png")
    subprocess.run([ff, "-y", "-framerate", str(FPS), "-start_number", "1", "-i", pat,
                    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(mp4)], check=True)
    # 600 px / 12 fps / 64 colours is about 9 MB; the 400 px one is for sites with tight limits.
    for px, fps, out in ((600, 12, gif), (400, 10, MEDIA / "claude-body-turntable-400.gif")):
        vf = (f"fps={fps},scale={px}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64:stats_mode=diff[p];"
              "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
        subprocess.run([ff, "-y", "-framerate", str(FPS), "-start_number", "1", "-i", pat,
                        "-vf", vf, "-loop", "0", str(out)], check=True)
    print("[turntable] wrote", mp4, "and the GIFs")


if __name__ == "__main__":
    if os.environ.get("TT_ENCODE_ONLY"):
        encode()
        sys.exit(0)
    sc = setup()
    sel = os.environ.get("TT_FRAMES")
    frames = [int(x) for x in sel.split(",")] if sel else list(range(1, LAST + 1))
    secs = render_frames(sc, frames)
    print(f"[turntable] rendered {len(frames)} frames in {secs:.0f}s ({secs / max(len(frames), 1):.1f}s/frame)")
    if not sel:
        encode()
