"""Claude's body — every printed part, plus envelopes of the bought parts, in the assembly frame.

Frame: X forward, Y left, Z up, origin on the floor under the axle centre. mm.

`printed()` returns {name: Part}; `vendor()` returns {name: Part} (envelopes, for fit checks and
renders only). Parts are modelled where they sit in the robot; build.py lays them flat to print.
"""
import math
from build123d import (Align, Axis, Box, Cone, Cylinder, Part, Plane, Polyline, Pos, Rot, Sphere,
                       Keep, extrude, fillet, make_face, revolve, split, Locations, Polygon,
                       PolarLocations, RectangleRounded, Vector, loft)
import params as P

C = (Align.CENTER, Align.CENTER, Align.MIN)


# ---------------------------------------------------------------- helpers
def cyl(r, h, x=0.0, y=0.0, z0=0.0):
    """Vertical cylinder standing on z0."""
    return Pos(x, y, z0) * Cylinder(r, h, align=C)


def box(lx, ly, lz, x=0.0, y=0.0, z0=0.0):
    """Box centred in XY, standing on z0."""
    return Pos(x, y, z0) * Box(lx, ly, lz, align=C)


def cyl_y(r, h, x=0.0, y0=0.0, z=0.0):
    """Cylinder along +Y starting at y0."""
    return Pos(x, y0, z) * Rot(-90, 0, 0) * Cylinder(r, h, align=C)


def cyl_x(r, h, x0=0.0, y=0.0, z=0.0):
    """Cylinder along +X starting at x0."""
    return Pos(x0, y, z) * Rot(0, 90, 0) * Cylinder(r, h, align=C)


def ring(r_out, r_in, h, x=0.0, y=0.0, z0=0.0):
    return cyl(r_out, h, x, y, z0) - cyl(r_in, h + 2, x, y, z0 - 1)


def insert_hole(x, y, z_top, depth=P.M3_INSERT_DEPTH):
    """Heat-set insert hole going DOWN from z_top."""
    return cyl(P.M3_INSERT_D / 2, depth, x, y, z_top - depth)


def frustum_shell(r0, r1, h, wall, z0):
    outer = Pos(0, 0, z0) * Cone(r0, r1, h, align=C)
    inner = Pos(0, 0, z0 - 0.01) * Cone(r0 - wall, r1 - wall, h + 0.02, align=C)
    return outer - inner


def revolve_profile(pts, cx=0.0, cy=0.0, cz=0.0):
    """Revolve a closed (r, z) profile about a vertical axis through (cx, cy)."""
    face = make_face(Polyline(*[(r, 0, z) for r, z in pts], close=True))
    return Pos(cx, cy, cz) * revolve(face, Axis.Z)


def involute_gear(teeth, module, thickness, bore=0.0, steps=6):
    """Spur gear, 20 deg pressure angle, polygonal involute (fine at 1 mm module for FDM)."""
    pa = math.radians(20)
    rp = teeth * module / 2
    rb = rp * math.cos(pa)
    ra = rp + module
    rf = max(rp - 1.25 * module, rb * 0.98)

    def inv(a):
        return math.tan(a) - a

    half_tooth = math.pi / (2 * teeth) + inv(pa)          # half tooth angle at base circle
    a_max = math.acos(rb / ra)
    pts = []
    for i in range(teeth):
        c = 2 * math.pi * i / teeth
        flank = []
        for s in range(steps + 1):
            a = a_max * s / steps
            r = rb / math.cos(a)
            flank.append((r, inv(a)))
        right = [(r, c - half_tooth + t) for r, t in flank]
        left = [(r, c + half_tooth - t) for r, t in reversed(flank)]
        pts.append((rf, c - half_tooth - 0.02))
        pts += right + left
        pts.append((rf, c + half_tooth + 0.02))
    xy = [(r * math.cos(t), r * math.sin(t)) for r, t in pts]
    g = extrude(make_face(Polyline(*xy, close=True)), thickness)
    if bore:
        g -= cyl(bore / 2, thickness + 2, z0=-1)
    return g


# ---------------------------------------------------------------- bought parts (envelopes)
def sts3215():
    """Local frame: output shaft along +Z, servo top face at z=0, tail towards +x."""
    tail = P.SERVO_L - P.SERVO_SHAFT_FROM_END
    body = Pos((tail - P.SERVO_SHAFT_FROM_END) / 2, 0, -P.SERVO_H) * Box(
        P.SERVO_L, P.SERVO_W, P.SERVO_H, align=C)
    horn = cyl(P.HORN_D / 2, P.HORN_T + 0.01, z0=-0.01)
    idler = cyl(P.HORN_D / 2, P.IDLER_T + 0.01, z0=-P.SERVO_H - P.IDLER_T)
    return body + horn + idler


def wheel_servo(side):
    s = 1 if side == "L" else -1
    face_y = s * (P.WHEEL_Y - P.WHEEL_W / 2 - P.HORN_T)          # horn face touches the hub
    rot = Rot(-90, 0, 0) if s > 0 else Rot(90, 0, 0)
    return Pos(0, face_y, P.AXLE_Z) * rot * Rot(0, 0, 180) * sts3215()


PI_X = -42.0                               # Pi 5 lies flat at the back of the body floor, clear of the intake fan
GEAR_TOP_Z = P.BODY_Z1 - 8.0               # gears + clutch cap hang under the lid's bearing boss
CLUTCH_FLANGE_T = 2.0
GEAR_Z0 = GEAR_TOP_Z - P.GEAR_T


def pan_servo():
    face_z = GEAR_Z0 - CLUTCH_FLANGE_T - P.HORN_T                 # clutch hub flange sits between horn and pinion
    return Pos(P.PAN_SERVO_X, 0, face_z) * Rot(0, 0, 90) * sts3215()


TILT_HORN_Y = 20.0                         # horn face inside the ball (+Y side)
XVF_X = P.HEAD_CX - 2.0
XVF_Z0 = P.HEAD_CZ + P.HEAD_H / 2 - P.HEAD_WALL - 18.0   # PCB underside; low enough that Ø100 clears the top fillets


def tilt_servo():
    # shaft along +Y on the tilt axis, long axis pointing down into the ball
    return Pos(0, TILT_HORN_Y - P.HORN_T, P.TILT_AXIS_Z) * Rot(-90, 0, 0) * Rot(0, 0, 90) * sts3215()


def vendor():
    v = {}
    v["servo_wheel_L"] = wheel_servo("L")
    v["servo_wheel_R"] = wheel_servo("R")
    v["servo_pan"] = pan_servo()
    v["servo_tilt"] = tilt_servo()
    v["battery_3s2p"] = box(P.PACK_L, P.PACK_W, P.PACK_H, x=P.PACK_X, z0=P.PACK_SHELF_Z + 0.5)
    v["lidar_stl19p"] = box(P.LIDAR_D, P.LIDAR_W, P.LIDAR_H - 12.7, z0=P.BAND_Z0 + 3) + cyl(35.3 / 2, 12.7, z0=P.BAND_Z0 + 3 + P.LIDAR_H - 12.7)
    v["pi5"] = box(56, 85, 24, x=PI_X, z0=P.BODY_Z0 + P.BODY_FLOOR_T + 6)
    v["screen_7in"] = facet_plane(0, SCREEN_VC, -P.SCREEN_GLASS_IN) * Box(P.SCREEN_W, P.SCREEN_H, P.SCREEN_T, align=(Align.CENTER, Align.CENTER, Align.MAX))
    v["m2_board"] = box(70, 90, 14, x=22, z0=P.BODY_Z0 + P.BODY_FLOOR_T + 6)          # Freenove M.2 board + SSD (UNCONFIRMED size)
    v["coral"] = box(65, 30, 8, x=25, y=65, z0=P.BODY_Z0 + P.BODY_FLOOR_T + 6)        # Coral USB (65 x 30 x 8)
    zs = BODY_SHELL_Z0 + P.SPK_DZ
    for s, n in ((1, "L"), (-1, "R")):
        yw = body_section(zs)[1] / 2 - P.BODY_WALL
        v[f"speaker_{n}"] = cyl_y(P.SPK_D / 2, P.SPK_T, x=P.SPK_X, y0=s * yw - (P.SPK_T if s > 0 else 0), z=zs)
    xb = -body_section(BODY_SHELL_Z0 + P.FAN_HIGH_DZ)[0] / 2 + P.BODY_WALL
    v["fan_exhaust"] = box(10, P.FAN_S, P.FAN_S, x=xb + 5.5, y=P.FAN_HIGH_Y, z0=BODY_SHELL_Z0 + P.FAN_HIGH_DZ - P.FAN_S / 2)
    for s in (1, -1):
        v[f"bearing_608_{'L' if s > 0 else 'R'}"] = Pos(0, s * (P.WHEEL_Y + P.WHEEL_W / 2 + 4 + P.BEARING_W / 2), P.AXLE_Z) * Rot(90, 0, 0) * (
            Cylinder(P.BEARING_OD / 2, P.BEARING_W) - Cylinder(P.BEARING_ID / 2, P.BEARING_W + 1))
        lift = P.CASTER_FRONT_LIFT if s > 0 else 0.0
        v[f"caster_ball_{'F' if s > 0 else 'R'}"] = Pos(P.CASTER_X_FRONT if s > 0 else -P.CASTER_X_REAR, 0, P.CASTER_BALL / 2 + lift) * Sphere(P.CASTER_BALL / 2)
        v[f"axle_pin_{'L' if s > 0 else 'R'}"] = cyl_y(P.AXLE_PIN_D / 2, P.AXLE_PIN_L, y0=(P.WHEEL_Y + P.WHEEL_W / 2 - 14) if s > 0 else -(P.WHEEL_Y + P.WHEEL_W / 2 - 14) - P.AXLE_PIN_L, z=P.AXLE_Z)
    v["pan_bearing_6806"] = ring(P.PAN_BRG_OD / 2, P.PAN_BRG_ID / 2, P.PAN_BRG_W, z0=P.LID_TOP - P.PAN_BRG_W)
    ez = P.HEAD_CZ + P.EYE_DZ
    face_x = P.HEAD_CX + P.HEAD_D / 2
    for s in (1, -1):
        v[f"lcd_{'L' if s > 0 else 'R'}"] = cyl_x(P.LCD_PCB_D / 2, P.LCD_DEPTH, x0=face_x - P.HEAD_WALL - P.LCD_DEPTH, y=s * P.EYE_Y, z=ez)
    v["camera_uvc"] = box(14, 32, 32, x=face_x - P.HEAD_WALL - 5.0 - 7, z0=P.HEAD_CZ + P.CAM_DZ - 16)   # USB UVC module (UNCONFIRMED size)
    for s in (1, -1):
        v[f"ear_servo_{'L' if s > 0 else 'R'}"] = box(22.8, 21.0, 12.2, P.EAR_X, s * (P.HEAD_W / 2 - P.HEAD_WALL - 0.5 - 10.5), P.EAR_Z - 6.1)   # MG90S (UNCONFIRMED)
    v["ballast_low"] = box(30, 36, 12, BALLAST_LOW_X, 0, P.CHASSIS_Z0 + P.CHASSIS_T + 0.5)   # ~100 g steel block under the battery shelf (REVIEW-2 #3)
    v["ballast_deck"] = box(30, 44, 14.5, -76, 0, P.DECK_Z0 - 14.5 - 0.5)   # ~150 g steel washers under the deck: below the COM, so it lowers it too
    v["xvf3800"] = cyl(P.XVF_D / 2, 6.0, x=XVF_X, z0=XVF_Z0) + cyl(28, 6.2, x=XVF_X, z0=XVF_Z0 - 6.2)
    for i, (r_, a) in enumerate(P.DROP_TOF_POS):
        v[f"tof_drop_{i}"] = Rot(0, 0, a) * box(13, 18, 3, r_, 0, P.DROP_TOF_Z)
    v["tof_head"] = box(3, 13, 18, face_x - P.HEAD_WALL - 4 - 1.5, 0, P.HEAD_CZ + P.HEAD_TOF_DZ - 9)
    for i, a in enumerate(P.FWD_TOF_ANGLES):
        v[f"tof_fwd_{i}"] = Rot(0, 0, a) * box(3, 13, 18, P.SKIRT_R - P.FWD_TOF_SETBACK - 1.5, 0, P.FWD_TOF_Z - 9)
    return v


# ---------------------------------------------------------------- base
def chassis_plate():
    z0, t = P.CHASSIS_Z0, P.CHASSIS_T
    plate = cyl(P.CHASSIS_R, t, z0=z0)
    # wheel wells
    for s in (1, -1):
        y0 = P.WHEEL_Y - P.WHEEL_W / 2 - P.WELL_CLEAR
        y1 = P.WHEEL_Y + P.WHEEL_W / 2 + P.WELL_CLEAR
        plate -= box(2 * (P.WHEEL_D / 2 + P.WELL_CLEAR), y1 - y0, t + 2, y=s * (y0 + y1) / 2, z0=z0 - 1)
    # standoffs up to the deck, with inserts in their tops
    for x, y in P.STANDOFF_XY:
        plate += cyl(P.STANDOFF_D / 2, P.DECK_Z0 - z0, x, y, z0)
        plate -= insert_hole(x, y, P.DECK_Z0)
    # wheel-servo cradles: U-channels round the servo body, strap screwed on top
    for side in ("L", "R"):
        s = 1 if side == "L" else -1
        sv = wheel_servo(side).bounding_box()
        cx, cy = (sv.min.X + sv.max.X) / 2, (sv.min.Y + sv.max.Y) / 2
        lx, ly = sv.max.X - sv.min.X, sv.max.Y - sv.min.Y
        h = P.AXLE_Z - (z0 + t)                    # up to the servo's mid-height
        horn_face = s * (P.WHEEL_Y - P.WHEEL_W / 2 - P.HORN_T)          # case top: the cradle ends 0.5 short of it
        y_out = horn_face - s * 0.5
        y_in = horn_face - s * (P.SERVO_H + P.IDLER_T + P.FIT + 3)
        cradle = box(lx + 2 * (P.FIT + 3), abs(y_out - y_in), h, cx, (y_out + y_in) / 2, z0 + t)
        cradle -= box(lx + 2 * P.FIT, ly + 2 * P.FIT, h + 1, cx, cy, sv.min.Z)
        plate += cradle
        for dx in (-lx / 2 - 1.5, lx / 2 + 1.5):
            plate -= insert_hole(cx + dx, cy, P.AXLE_Z)
        # outboard bearing arm at X=0, outside the wheel; a steel pin from the hub runs in its 608
        y_in = s * (P.WHEEL_Y + P.WHEEL_W / 2 + 3)
        arm_w = P.BEARING_W + 3
        arm_y = y_in + s * arm_w / 2
        plate += box(14, arm_w, P.AXLE_Z - z0, 0, arm_y, z0)
        plate += Pos(0, arm_y, P.AXLE_Z) * Rot(90, 0, 0) * Cylinder(P.BEARING_OD / 2 + 3, arm_w)
        plate -= Pos(0, arm_y, P.AXLE_Z) * Rot(90, 0, 0) * Cylinder(P.BEARING_OD / 2 + 0.05, arm_w + 2)  # press fit
    # battery shelf above the rear caster: puts the centre of mass well behind the axle
    bx = P.PACK_X
    sx0, sx1 = bx - P.PACK_L / 2 - 3, bx + P.PACK_L / 2 + 3
    shelf_t = 3.0
    shelf = box(sx1 - sx0, 64, shelf_t, (sx0 + sx1) / 2, 0, P.PACK_SHELF_Z - shelf_t)
    for dx in (-18, 18):                                                         # hook-and-loop strap slots
        shelf -= box(20, 3, shelf_t + 2, bx + dx, 0, P.PACK_SHELF_Z - shelf_t - 1)
    for dx in (-(P.PACK_L / 2 + P.LOOSE + 1.5), P.PACK_L / 2 + P.LOOSE + 1.5):
        shelf += box(3, P.PACK_W - 10, 10, bx + dx, 0, P.PACK_SHELF_Z)            # end stops
    for lx_, ly_ in ((sx0 + 4, 26), (sx0 + 4, -26), (sx1 - 4, 20), (sx1 - 4, -20)):
        shelf += cyl(3.5, P.PACK_SHELF_Z - (z0 + t), lx_, ly_, z0 + t)
    plate += shelf
    for by in (-10, 10):                                                         # low steel ballast block, 2 x M4 from below
        plate -= cyl(2.25, t + 2, BALLAST_LOW_X, by, z0 - 1)
    # ball casters: ball passes through the plate; housing above, retainer below (3 x M3 through all)
    for cxp in (P.CASTER_X_FRONT, -P.CASTER_X_REAR):
        plate -= cyl(P.CASTER_BALL / 2 + 1.0, t + 2, cxp, 0, z0 - 1)
        for loc in PolarLocations(CASTER_SCREW_R, 3, 90):
            p = loc.position
            plate -= cyl(P.M3_CLEAR / 2, t + 2, cxp + p.X, p.Y, z0 - 1)
    # drop sensors look down through the plate from towers (VL53L1X needs >= 40 mm to the floor)
    for r_, a in P.DROP_TOF_POS:
        x, y = r_ * math.cos(math.radians(a)), r_ * math.sin(math.radians(a))
        tower = Rot(0, 0, a) * (box(16.4, 22.4, P.DROP_TOF_Z - z0, r_, 0, z0)
                                - box(13.2, 19.2, P.DROP_TOF_Z - z0 + 2, r_, 0, z0 - 1)
                                - box(20, 8, 12, r_, 0, P.DROP_TOF_Z - 12))       # wire exit
        plate += tower
        plate -= cyl(6.5, t + 2, x, y, z0 - 1)                  # 27 deg cone clears the plate
        for d in (-P.POLOLU_TOF_HOLES / 2, P.POLOLU_TOF_HOLES / 2):
            plate += Rot(0, 0, a) * (box(16.4, 3.6, 3, r_, d, P.DROP_TOF_Z - 3) - box(1.6, 1.6, 4, r_, d, P.DROP_TOF_Z - 3.5))
    # forward low-obstacle sensors: upright tabs set back FWD_TOF_SETBACK from the bumper face
    for a in P.FWD_TOF_ANGLES:
        r = P.SKIRT_R - P.FWD_TOF_SETBACK - 3 - 1.5
        tab = box(3, 16, P.FWD_TOF_Z + 11 - (z0 + t), r, 0, z0 + t)
        tab -= cyl_x(6, 6, x0=r - 3, z=P.FWD_TOF_Z)
        for d in (-P.POLOLU_TOF_HOLES / 2, P.POLOLU_TOF_HOLES / 2):
            tab -= cyl_x(0.8, 6, x0=r - 3, y=d, z=P.FWD_TOF_Z + 7.5)
        plate += Rot(0, 0, a) * tab
    # bumper guide: shoulder-screw insert bosses (bumper tabs slide on these, parallel to X)
    for a in P.BUMPER_TAB_ANGLES:
        x, y = bumper_screw_xy(a)
        plate += cyl(5, 6, x, y, z0 + t)
        plate -= insert_hole(x, y, z0 + t + 6)
    # bumper switch blocks: a 20 x 6.4 x 10 micro switch screws to the outer face (2 x M2, 9.5 apart),
    # with a Ø5.5 pocket beside it for the return spring. The bumper's striker meets the lever.
    for a in P.BUMPER_SWITCH_ANGLES:
        r = SWITCH_BLOCK_R
        sg = 1 if a > 0 else -1                 # switch on the side away from the drop tower
        blk = box(8, 16, 14, r, 0, z0 + t)
        # micro switch lies against the block's side face, button edge facing outwards to the striker
        for dz in (2.25, 11.75):
            blk -= cyl_y(0.9, 10, x=r - 1, y0=-5 if sg > 0 else -5, z=z0 + t + dz)       # M2 self-tap, 9.5 apart
        blk -= cyl_x(2.75, 3.01, x0=r + 4 - 3, y=-sg * 4, z=z0 + t + 7)                  # spring seat (3 deep)
        plate += Rot(0, 0, a) * blk
    # cable pass for the floor ToFs / wheel servos
    plate -= box(30, 12, t + 2, 40, 0, z0 - 1)
    # front arc of the plate cut back to r 111 so the bumper (inner r 115) can travel 4 mm (REVIEW-2 #2)
    plate -= ring(P.SKIRT_R + 5, CHASSIS_FRONT_R, t + 2, z0=z0 - 1) & wedge_z(-P.BUMPER_ARC / 2 - 2, P.BUMPER_ARC / 2 + 2, z0 - 2, t + 4)
    return plate


CHASSIS_FRONT_R = 111.0


def wedge_z(a0, a1, z0, h):
    pts = [(0, 0)] + [(400 * math.cos(math.radians(a0 + (a1 - a0) * i / 24)),
                       400 * math.sin(math.radians(a0 + (a1 - a0) * i / 24))) for i in range(25)]
    return Pos(0, 0, z0) * extrude(make_face(Polyline(*pts, close=True)), h)


SWITCH_BLOCK_R = 98.0
BALLAST_LOW_X = -45.0


def bumper_screw_xy(a):
    r = P.CHASSIS_R - 8
    return r * math.cos(math.radians(a)), r * math.sin(math.radians(a))


def skirt_shells():
    """Rear skirt (fixed) and front bumper (slides back BUMPER_TRAVEL onto two switches)."""
    z0, z1 = P.SKIRT_Z0, P.SKIRT_Z1
    h = z1 - z0
    shell = cyl(P.SKIRT_R, h, z0=z0) - cyl(P.SKIRT_R - P.SKIRT_WALL, h + 2, z0=z0 - 1)
    shell = fillet(shell.edges().filter_by(Axis.Z, reverse=True).sort_by(Axis.Z)[:1], 2.5)
    half = P.BUMPER_ARC / 2
    gap = 5.0                                   # air at each end: more than the 3.5 mm travel (REVIEW-2 #2)
    def wedge(a0, a1):
        pts = [(0, 0)] + [(400 * math.cos(math.radians(a0 + (a1 - a0) * i / 24)),
                           400 * math.sin(math.radians(a0 + (a1 - a0) * i / 24))) for i in range(25)]
        return Pos(0, 0, z0 - 5) * extrude(make_face(Polyline(*pts, close=True)), h + 10)
    g = math.degrees(gap / P.SKIRT_R)
    bumper = shell & wedge(-half + g / 2, half - g / 2)
    rear = shell & wedge(half + g / 2, 360 - half - g / 2)
    # bumper tabs: lugs at the bottom riding on M3 screws with Ø4 sleeves in the chassis bosses.
    # Every slot runs parallel to X (the direction the bumper moves), whatever angle its lug is at.
    lug_z = P.CHASSIS_Z0 + P.CHASSIS_T + 6.5
    sleeve = 4.0
    for a in P.BUMPER_TAB_ANGLES:
        r = P.CHASSIS_R - 8
        x, y = bumper_screw_xy(a)
        lug_r_out = P.SKIRT_R - P.SKIRT_WALL + 0.1
        bumper += Rot(0, 0, a) * box(lug_r_out - r + 9, 14, 3, (lug_r_out + r - 9) / 2, 0, lug_z)
        bumper -= box(sleeve + 2 * P.BUMPER_TRAVEL + 1.0, sleeve + 2 * P.BUMPER_SLOT_SIDE, 5,
                      x + P.BUMPER_TRAVEL / 2, y, lug_z - 1)
    # strikers: on the bumper's inner face, over the switch button (1 mm pre-travel) and the spring
    # (5 x 15 mm spring: 3 mm seat in the block + 8 mm pocket here = 13.5 mm at rest, 10 at full travel)
    for a in P.BUMPER_SWITCH_ANGLES:
        r_in = P.SKIRT_R - P.SKIRT_WALL
        sg = 1 if a > 0 else -1
        st_r0 = SWITCH_BLOCK_R + 4 + 2.5                               # switch button edge ~r 104.5 + 1 mm
        st = box(r_in + 1 - st_r0, 20.5, 12, (r_in + 1 + st_r0) / 2, sg * 4.75, P.CHASSIS_Z0 + P.CHASSIS_T + 1)
        st -= cyl_x(2.75, 8.01, x0=st_r0, y=-sg * 4, z=P.CHASSIS_Z0 + P.CHASSIS_T + 7)
        bumper += (Rot(0, 0, a) * st) & cyl(P.SKIRT_R - 0.5, 60, z0=0)
    # forward low-obstacle sensor windows (bigger than the bumper travel)
    for a in P.FWD_TOF_ANGLES:
        bumper -= Rot(0, 0, a) * cyl_x(9, 10, x0=P.SKIRT_R - 6, z=P.FWD_TOF_Z)
    # rear skirt: charge contacts, motor kill switch, tabs to the chassis
    for y in (-20, 20):
        rear -= cyl_x(4.2, 10, x0=-P.SKIRT_R - 2, y=y, z=30)
    rear -= Rot(0, 0, 200) * box(10, 19.5, 13.5, P.SKIRT_R - 1, 0, 64)  # rocker (UNCONFIRMED 19x13 cut-out)
    for a in (150, 180, 210):
        tab = box(10, 12, 4, P.SKIRT_R - P.SKIRT_WALL - 4, 0, P.DECK_Z0 - 4)
        tab -= cyl(P.M3_CLEAR / 2, 6, P.SKIRT_R - P.SKIRT_WALL - 5, 0, P.DECK_Z0 - 5)
        rear += Rot(0, 0, a) * tab
    return bumper, rear


def wheel_hub(side):
    s = 1 if side == "L" else -1
    r_hub = P.WHEEL_D / 2 - P.TYRE_T
    y0 = P.WHEEL_Y - P.WHEEL_W / 2
    hub = cyl_y(r_hub, P.WHEEL_W, y0=y0, z=P.AXLE_Z)
    # lightening: 5 round windows, rim + web stay >= 3 mm
    for i in range(5):
        a = 2 * math.pi * i / 5 + math.pi / 2
        hub -= cyl_y(12, P.WHEEL_W + 2, x=26 * math.cos(a), y0=y0 - 1, z=P.AXLE_Z + 26 * math.sin(a))
    # tyre retention grooves (TPU tyre has matching ribs)
    for dy in (5, P.WHEEL_W - 5):
        hub -= cyl_y(r_hub + 1, 2, y0=y0 + dy - 1, z=P.AXLE_Z) - cyl_y(r_hub - 1.2, 2, y0=y0 + dy - 1, z=P.AXLE_Z)
    # horn interface: flat face on the horn, 4 x M2.5 on the 14 mm circle, heads recessed outboard
    hub -= cyl_y(1.6, 3.0, y0=y0 - 0.01, z=P.AXLE_Z)                       # clears the horn's centre screw head
    for loc in PolarLocations(P.HORN_HOLE_R, 4, 45):
        p = loc.position
        hub -= cyl_y(P.HORN_SCREW_CLEAR / 2, P.WHEEL_W + 2, x=p.X, y0=y0 - 1, z=P.AXLE_Z + p.Y)
        hub -= cyl_y(2.6, P.WHEEL_W - 6, x=p.X, y0=y0 + 6, z=P.AXLE_Z + p.Y)   # long-driver access, 6 mm of thread grip left
    # steel axle pin (8 mm dowel or cut M8 bolt) pressed into a blind hole: printed stubs fatigue across layers
    hub -= cyl_y(P.AXLE_PIN_D / 2 - 0.1, 14, y0=y0 + P.WHEEL_W - 14, z=P.AXLE_Z)
    return hub if s > 0 else hub.mirror(Plane.XZ)


def tyre(side):
    s = 1 if side == "L" else -1
    r_hub = P.WHEEL_D / 2 - P.TYRE_T
    y0 = P.WHEEL_Y - P.WHEEL_W / 2
    t = cyl_y(P.WHEEL_D / 2, P.WHEEL_W, y0=y0, z=P.AXLE_Z) - cyl_y(r_hub - 0.6, P.WHEEL_W + 2, y0=y0 - 1, z=P.AXLE_Z)  # 0.6 stretch
    for dy in (5, P.WHEEL_W - 5):
        t += cyl_y(r_hub - 0.6, 2 - 2 * P.FIT, y0=y0 + dy - 1 + P.FIT, z=P.AXLE_Z) - cyl_y(r_hub - 2.0, 3, y0=y0 + dy - 1.5, z=P.AXLE_Z)
    # shallow tread grooves
    for i in range(36):
        t -= Pos(0, 0, P.AXLE_Z) * Rot(0, 360 * i / 36, 0) * box(2.0, P.WHEEL_W - 6, 2.0, P.WHEEL_D / 2, (y0 + P.WHEEL_W / 2), -1)
    return t if s > 0 else t.mirror(Plane.XZ)


CASTER_SCREW_R = P.CASTER_BALL / 2 + 6.0


CASTER_SCREW_R = P.CASTER_BALL / 2 + 6.0


def caster_parts(front):
    """Printed ball caster: housing on top of the plate, retainer ring under it, 1in steel ball between.
    The front one carries its ball 3 mm higher, so it only touches when the robot pitches forward.
    Tune the split with 0.5 mm shim washers under the housing once the real centre of mass is known."""
    x = P.CASTER_X_FRONT if front else -P.CASTER_X_REAR
    lift = P.CASTER_FRONT_LIFT if front else 0.0
    bz = P.CASTER_BALL / 2 + lift                       # ball centre height
    rb = P.CASTER_BALL / 2
    top = P.CHASSIS_Z0 + P.CHASSIS_T
    housing = cyl(CASTER_SCREW_R + 4.5, bz + rb + 3 - top, x, 0, top)
    housing -= Pos(x, 0, bz) * Sphere(rb + 0.35)          # running clearance (housing side only)
    housing -= cyl(1.5, 10, x, 0, bz + rb - 1)            # grease / dirt vent
    ret_z1 = P.CHASSIS_Z0
    ret_z0 = max(bz - rb * 0.55, 3.0)
    chord = 2 * math.sqrt(rb ** 2 - (bz - ret_z0) ** 2)   # ball width at the retainer's lower lip
    retainer = cyl(CASTER_SCREW_R + 4.5, ret_z1 - ret_z0, x, 0, ret_z0)
    retainer -= Pos(x, 0, bz) * Sphere(rb + 0.35)
    retainer -= cyl(chord / 2 - 0.6, 20, x, 0, ret_z0 - 1)  # lip narrower than the ball = it can't drop out
    for loc in PolarLocations(CASTER_SCREW_R, 3, 90):
        p = loc.position
        housing -= cyl(P.M3_CLEAR / 2, 40, x + p.X, p.Y, top - 1)
        housing -= cyl(P.M3_HEAD_D / 2 + 0.3, 20, x + p.X, p.Y, bz + rb + 3 - 3)
        retainer -= cyl(P.M3_INSERT_D / 2, 20, x + p.X, p.Y, ret_z0 + 1.2)
    return housing, retainer


PILLAR_PAD_H = 6.0                 # pads sit above the lidar's laser band


def pillar_insert_xy(a):
    out = []
    for d in (-6.9, 6.9):
        x = P.PILLAR_R * math.cos(math.radians(a)) - d * math.sin(math.radians(a))
        y = P.PILLAR_R * math.sin(math.radians(a)) + d * math.cos(math.radians(a))
        out.append((x, y))
    return out


def waist_deck():
    z0, t = P.DECK_Z0, P.DECK_T
    deck = cyl(P.DECK_R, t, z0=z0)
    for x, y in P.STANDOFF_XY:
        deck -= cyl(P.M3_CLEAR / 2, t + 2, x, y, z0 - 1)
        deck -= cyl(P.M3_HEAD_D / 2 + 0.3, 3, x, y, z0 + t - 2)  # counterbore so the lidar sits flat
    for a in (150, 180, 210):                                     # rear-skirt tabs screw up into the deck
        r = P.SKIRT_R - P.SKIRT_WALL - 5
        deck -= insert_hole(r * math.cos(math.radians(a)), r * math.sin(math.radians(a)), z0 + 4.5, 4.5)
    # bumper top guide: a lip under the deck's front edge stops a kick on the bumper's top edge
    # levering it off its lugs, and doubles as the bumper's travel stop
    half = P.BUMPER_ARC / 2 - 4
    lip = ring(P.SKIRT_R - P.SKIRT_WALL - P.BUMPER_TRAVEL - 0.5, P.SKIRT_R - P.SKIRT_WALL - P.BUMPER_TRAVEL - 2.5, 8, z0=z0 - 8)
    pts = [(0, 0)] + [(400 * math.cos(math.radians(-half + 2 * half * i / 24)),
                       400 * math.sin(math.radians(-half + 2 * half * i / 24))) for i in range(25)]
    deck += lip & (Pos(0, 0, z0 - 10) * extrude(make_face(Polyline(*pts, close=True)), 20))
    # lidar: 3 x M2.5 — front pair 46.8 apart, third centred 31.92 behind (STL-19P / LD19 drawing)
    fx = P.LIDAR_HOLE_BACK / 2
    for hx, hy in ((fx, -P.LIDAR_HOLE_FRONT_SPAN / 2), (fx, P.LIDAR_HOLE_FRONT_SPAN / 2), (fx - P.LIDAR_HOLE_BACK, 0)):
        deck += cyl(3.2, 3, hx, hy, z0 + t)
        deck -= cyl(P.M2_5_CLEAR / 2, t + 6, hx, hy, z0 - 1)
    deck -= box(16, 10, t + 2, -P.LIDAR_D / 2 - 14, 0, z0 - 1)
    for by in (-12, 12):                                          # deck ballast: 2 x M4 through the deck
        deck -= cyl(2.25, t + 2, -76, by, z0 - 1)
    # three hollow pillars up to the body floor (cable chases); a wider pad on top carries 2 inserts each
    top = P.BODY_Z0
    for a in P.PILLAR_ANGLES:
        pillar = Rot(0, 0, a) * box(P.PILLAR_W * 1.6, P.PILLAR_W, top - (z0 + t), P.PILLAR_R, 0, z0 + t)
        pillar = fillet(pillar.edges().filter_by(Axis.Z), 2.5)
        pad = Rot(0, 0, a) * box(P.PILLAR_W * 1.6, 21, PILLAR_PAD_H, P.PILLAR_R, 0, top - PILLAR_PAD_H)
        deck += pillar + pad
        deck -= Rot(0, 0, a) * box(P.PILLAR_W * 1.6 - 3.2, P.PILLAR_W - 3.2, top - z0 + 2, P.PILLAR_R, 0, z0 - 1)
        for x, y in pillar_insert_xy(a):
            deck -= insert_hole(x, y, top)
    return deck


# ---------------------------------------------------------------- body column (abdomen)
BODY_SHELL_Z0 = P.BODY_Z0 + P.BODY_FLOOR_T     # the shell stands on the floor plate


def body_section(z):
    """(depth, width, corner r) of the abdomen's outside at height z (linear between bottom and top)."""
    f = (z - BODY_SHELL_Z0) / P.BODY_H
    return (P.BODY_D0 + (P.BODY_D1 - P.BODY_D0) * f, P.BODY_W0 + (P.BODY_W1 - P.BODY_W0) * f,
            P.BODY_CR0 + (P.BODY_CR1 - P.BODY_CR0) * f)


def body_box(inset=0.0, z0=None, z1=None):
    """The abdomen's rounded-box volume, `inset` inside its outer surface, from z0 to z1."""
    z0 = BODY_SHELL_Z0 if z0 is None else z0
    z1 = P.BODY_Z1 if z1 is None else z1
    secs = []
    for z in (z0, z1):
        d, w, r = body_section(z)
        secs.append(Plane.XY.offset(z) * RectangleRounded(d - 2 * inset, w - 2 * inset, max(r - inset, 1.0)))
    return loft(secs)


def facet_n():
    t = math.radians(P.SCREEN_TILT)
    return Vector(math.cos(t), 0, math.sin(t))


def facet_pt(u, v, d=0.0):
    """A point on the screen face: u across (+Y), v up the slope from the floor, d along the outward
    normal (0 = the face's outer surface, negative = inside)."""
    t = math.radians(P.SCREEN_TILT)
    up = Vector(-math.sin(t), 0, math.cos(t))
    return Vector(P.FACET_X0, 0, BODY_SHELL_Z0) + Vector(0, u, 0) + up * v + facet_n() * d


def facet_plane(u=0.0, v=0.0, d=0.0):
    return Plane(origin=facet_pt(u, v, d), x_dir=(0, 1, 0), z_dir=facet_n())


def behind_facet(shape, d=0.0):
    """Keep only what is behind the screen face (offset d along its normal)."""
    return split(shape, facet_plane(d=d), keep=Keep.BOTTOM)


SCREEN_VC = P.SCREEN_V0 + P.SCREEN_H / 2                     # screen centre, up the face
SCREEN_BACK_D = -P.SCREEN_GLASS_IN - P.SCREEN_T             # the screen's back, along the face normal
SCREEN_BOSSES = [(s * (P.SCREEN_W / 2 + 5), SCREEN_VC + dv) for s in (1, -1) for dv in (-35.0, 35.0)] + \
                [(0.0, SCREEN_VC - P.SCREEN_H / 2 - 5), (0.0, SCREEN_VC + P.SCREEN_H / 2 + 5)]


def facet_cyl(u, v, r, d0, d1):
    """Cylinder along the face normal from depth d0 to d1 (d1 > d0)."""
    return facet_plane(u, v, d0) * Cylinder(r, d1 - d0, align=C)


def body_bosses(z):
    """Shell screw positions at height z: (x, y, wall direction). Two each side, two at the back;
    none on the X=0 seam, none in front of the screen face."""
    d, w, _ = body_section(z)
    yi, xb = w / 2 - P.BODY_WALL - 4.5, -(d / 2 - P.BODY_WALL - 4.5)
    pts = [(x, s * yi, (0, s)) for x in (15.0, -35.0) for s in (1, -1)]
    return pts + [(xb, s * 48.0, (-1, 0)) for s in (1, -1)]


def hex_holes(r_area, hole_d, pitch):
    """(a, b) centres of a hex hole pattern inside a circle of radius r_area."""
    n = int(r_area // pitch) + 1
    out = []
    for j in range(-n, n + 1):
        for i in range(-n, n + 1):
            a, b = i * pitch + (pitch / 2 if j % 2 else 0), j * pitch * 0.866
            if math.hypot(a, b) <= r_area - hole_d / 2:
                out.append((a, b))
    return out


def body_floor():
    z0, t = P.BODY_Z0, P.BODY_FLOOR_T
    d, w, r = body_section(BODY_SHELL_Z0)
    f = behind_facet(Pos(0, 0, z0) * extrude(RectangleRounded(d, w, r), t))
    for a in P.PILLAR_ANGLES:                                     # cable chases + 2 screws into each pillar pad
        f -= Rot(0, 0, a) * box(P.PILLAR_W * 1.6 - 3.2, P.PILLAR_W - 3.2, t + 2, P.PILLAR_R, 0, z0 - 1)
        for x, y in pillar_insert_xy(a):
            f -= cyl(P.M3_CLEAR / 2, t + 2, x, y, z0 - 1)
            f -= cyl(P.M3_HEAD_D / 2 + 0.3, 2, x, y, z0 + t - 1.5)
    # Pi 5 bosses: 58 x 49 M2.5 (board turned 90 deg: long side along Y)
    for dx in (-24.5, 24.5):
        for dy in (-29, 29):
            f += cyl(3, 6, PI_X + dx, dy, z0 + t)
            f -= cyl(1.25, 6, PI_X + dx, dy, z0 + t + 0.5)
    # M3 insert grid for the M.2 board, Coral and USB parts (their sizes aren't measured yet)
    for x in (0.0, 20.0, 40.0):
        for y in (-60.0, -30.0, 0.0, 30.0, 60.0):
            f += cyl(3.5, 5, x, y, z0 + t)
            f -= cyl(P.M3_INSERT_D / 2, 5, x, y, z0 + t + 1)
    ix, iy = P.FLOOR_INTAKE_XY                                    # passive intake: cool air up from the base
    for a_, b_ in hex_holes(18.0, 4.0, 4.0 + P.MIN_WEB + 0.3):
        f -= cyl(2.0, t + 2, ix + a_, iy + b_, z0 - 1)
    for x, y, _ in body_bosses(BODY_SHELL_Z0):                    # shell screws come up through the floor
        f -= cyl(P.M3_CLEAR / 2, t + 2, x, y, z0 - 1)
        f -= cyl(P.M3_HEAD_D / 2 + 0.3, 2, x, y, z0 - 0.5)
    return f


def body_shells():
    z0, z1 = BODY_SHELL_Z0, P.BODY_Z1
    outer = body_box()
    inner = body_box(P.BODY_WALL, z0 - 1, z1 + 1)
    shell = behind_facet(outer - inner)
    # the screen face: a wall BODY_WALL thick on the slope
    face = split(behind_facet(outer), facet_plane(d=-P.BODY_WALL), keep=Keep.TOP)
    shell += face
    # screen window, and a pocket on the inside that locates the glass
    shell -= facet_plane(0, SCREEN_VC, -5) * extrude(RectangleRounded(P.SCREEN_VIEW_W, P.SCREEN_VIEW_H, 3), 10)
    shell -= facet_plane(0, SCREEN_VC, -P.BODY_WALL - 0.5) * extrude(
        RectangleRounded(P.SCREEN_W + 0.6, P.SCREEN_H + 0.6, 2), P.BODY_WALL + 0.5 - P.SCREEN_GLASS_IN)
    # clamp bosses behind the face: the screen_clamp screws to their ends, pressing the screen's back edge
    for u, v in SCREEN_BOSSES:
        shell += facet_cyl(u, v, 4.0, SCREEN_BACK_D, -P.BODY_WALL + 0.5)
        shell -= facet_cyl(u, v, P.M3_INSERT_D / 2, SCREEN_BACK_D - 0.1, SCREEN_BACK_D + P.M3_INSERT_DEPTH)
    # screw bosses at the bottom (into the floor) and top (lid); inserts
    holes = []
    for zb, up in ((z0, True), (z1, False)):
        for x, y, (dx, dy) in body_bosses(zb):
            zb0 = zb if up else zb - 10
            b = cyl(4.5, 10, x, y, zb0)
            b += box(9 if dx == 0 else 6, 6 if dx == 0 else 9, 10, x + dx * 3, y + dy * 3, zb0)
            shell += b & outer
            holes.append(insert_hole(x, y, zb + P.M3_INSERT_DEPTH) if up else insert_hole(x, y, zb))
    for h in holes:
        shell -= h
    # exhaust fan grille high on the back, and a USB-C service hole
    xb = -body_section(z0 + P.FAN_HIGH_DZ)[0] / 2
    for a_, b_ in hex_holes(P.FAN_S / 2 - 2, 3.5, 3.5 + P.MIN_WEB + 0.3):
        shell -= cyl_x(1.75, 12, x0=xb - 6, y=P.FAN_HIGH_Y + a_, z=z0 + P.FAN_HIGH_DZ + b_)
    shell -= cyl_x(5, 12, x0=-body_section(z0 + 20)[0] / 2 - 6, y=-55, z=z0 + 20)
    # side speaker grilles (Z200 drivers fire sideways)
    zs = z0 + P.SPK_DZ
    for s in (1, -1):
        yw = body_section(zs)[1] / 2
        for a_, b_ in hex_holes(P.SPK_D / 2 - 4, 4.0, 4.0 + P.MIN_WEB + 0.3):
            if abs(P.SPK_X + a_) < 3.5:                             # solid strip on the front/back seam
                continue
            shell -= cyl_y(2.0, 12, x=P.SPK_X + a_, y0=s * yw - 6, z=zs + b_)
    front = split(shell, Plane.YZ, keep=Keep.TOP)
    back = split(shell, Plane.YZ, keep=Keep.BOTTOM)
    # seam tabs at mid-height on both sides: part of the front half, reaching 10 mm into the back half;
    # an M3 through the back half's wall into an insert in each tab holds the seam closed
    zm = z0 + 100                                                # above the speakers
    yi = body_section(zm + 8)[1] / 2 - P.BODY_WALL
    for s in (1, -1):
        fused = box(10, 8, 16, 5, s * (yi - 3.5), zm)               # overlaps the front wall by 0.5
        reach = box(10, 8, 16, -5, s * (yi - 4.3), zm)              # 0.3 mm off the back half's wall
        tab = (fused + reach) & outer
        tab -= cyl_y(P.M3_INSERT_D / 2, 6, x=-5, y0=s * (yi - 0.3) - (6 if s > 0 else 0), z=zm + 8)
        front += tab
        back -= cyl_y(P.M3_CLEAR / 2, 8, x=-5, y0=s * (yi - 1) - (0 if s > 0 else 8), z=zm + 8)
    front = Part(max(front.solids(), key=lambda s_: s_.volume).wrapped)   # drop any zero-volume sliver
    back = Part(max(back.solids(), key=lambda s_: s_.volume).wrapped)
    return front, back


def screen_clamp():
    """Frame that presses the 7" screen's back edge into its pocket; 6 x M3 into the face bosses."""
    t = 2.5
    c = facet_plane(0, SCREEN_VC, SCREEN_BACK_D - t) * extrude(
        RectangleRounded(P.SCREEN_W + 18, P.SCREEN_H + 18, 6) - RectangleRounded(P.SCREEN_W - 14, P.SCREEN_H - 14, 4), t)
    for u, v in SCREEN_BOSSES:
        c -= facet_cyl(u, v, P.M3_CLEAR / 2, SCREEN_BACK_D - t - 1, SCREEN_BACK_D + 1)
    return c & body_box(P.BODY_WALL + 0.5)


def body_lid():
    z0 = P.BODY_Z1
    d, w, r = body_section(z0)
    lid = behind_facet(Pos(0, 0, z0) * extrude(RectangleRounded(d, w, r), P.LID_T))
    for x, y, _ in body_bosses(z0):
        lid -= cyl(P.M3_CLEAR / 2, 10, x, y, z0 - 1)
        lid -= cyl(P.M3_HEAD_D / 2 + 0.3, 2, x, y, z0 + P.LID_T - 1.5)
    # 6806 bearing boss: pocket from the top, retaining lip at the bottom
    lid += cyl(P.PAN_BRG_OD / 2 + 4, P.PAN_BRG_W + 1 - P.LID_T, z0=z0 - (P.PAN_BRG_W + 1 - P.LID_T))
    lid -= cyl(P.PAN_BRG_OD / 2 + 0.05, P.PAN_BRG_W + 1, z0=P.LID_TOP - P.PAN_BRG_W)       # light press
    lid -= cyl(P.PAN_BRG_OD / 2 - 3, 20, z0=z0 - 10)                                    # lip touches outer race only
    # pan-servo hanger: two drop plates either side of the servo, clear of both gears
    sv = pan_servo().bounding_box()
    gear_r = P.GEAR_TEETH * P.GEAR_MODULE / 2 + P.GEAR_MODULE + 1.5
    y_lo, y_hi = min(sv.min.Y - P.FIT, -gear_r) - 3, max(sv.max.Y + P.FIT, gear_r) + 3
    for sy in (y_lo, y_hi - 3):
        hang_h = z0 - sv.min.Z
        lid += box(sv.max.X - sv.min.X + 6, 3, hang_h, (sv.min.X + sv.max.X) / 2, sy + 1.5, sv.min.Z)
    lid += box(sv.max.X - sv.min.X + 6, y_hi - y_lo, 3, (sv.min.X + sv.max.X) / 2, (y_lo + y_hi) / 2, sv.min.Z - 3)
    return lid


# ---------------------------------------------------------------- neck


def ball_bowl():
    """Pan frame: post (through the 6806) + collar + lower ball. Holds the tilt servo, and carries
    the two hard-stop lugs for tilt on its outside beside the -Y hub."""
    c = P.TILT_AXIS_Z
    split_z = c + P.BALL_SPLIT_DZ
    ball = Pos(0, 0, c) * Sphere(P.BALL_R) - Pos(0, 0, c) * Sphere(P.BALL_R - P.BALL_WALL)
    ball = ball - box(200, 200, 200, z0=split_z)
    post_z0 = GEAR_TOP_Z
    post = cyl(P.POST_R - 0.05, c - post_z0, z0=post_z0)              # slip into the 6806 bore
    collar = revolve_profile([(P.POST_R - 1, P.COLLAR_Z0), (P.COLLAR_R, P.COLLAR_Z0),
                              (P.COLLAR_R, P.COLLAR_Z0 + 1.0), (P.POST_R, P.COLLAR_Z0 + 1.0 + P.COLLAR_R - P.POST_R),
                              (P.POST_R - 1, P.COLLAR_Z0 + 1.0 + P.COLLAR_R - P.POST_R)])
    shoulder = ring(P.POST_R + 2.5, P.POST_R - 1, P.NECK_GAP, z0=P.LID_TOP)  # rests on the inner race only
    bowl = ball + post + collar + shoulder
    bowl -= cyl(P.POST_BORE / 2, c - post_z0 + 10, z0=post_z0 - 1)
    for loc in PolarLocations(P.POST_R - 4.5, 3, 0):
        p = loc.position
        bowl -= insert_hole(p.X, p.Y, post_z0 + P.M3_INSERT_DEPTH)            # gear screws up into the post end
    bowl -= Pos(0, 0, c) * Sphere(P.BALL_R - P.BALL_WALL)                  # keep the inside clear
    # hub openings on the tilt axis
    bowl -= cyl_y(P.BALL_HOLE_D / 2, 20, y0=P.BALL_R - 12, z=c)
    bush = cyl_y(P.HUB_D / 2 + 4, 8, y0=-P.BALL_R + 0.5, z=c) & (Pos(0, 0, c) * Sphere(P.BALL_R - 0.5))
    bowl += bush
    bowl -= cyl_y(P.HUB_D / 2 + P.FIT, 20, y0=-P.BALL_R - 5, z=c)          # bushing bore (clearance on this side only)
    # tilt-servo cradle off the bowl floor
    sv = tilt_servo().bounding_box()
    cx, cy = (sv.min.X + sv.max.X) / 2, (sv.min.Y + sv.max.Y) / 2
    lx, ly = sv.max.X - sv.min.X, sv.max.Y - sv.min.Y
    cradle_z0 = c - math.sqrt((P.BALL_R - P.BALL_WALL) ** 2 - (lx / 2 + 3) ** 2) - 1
    cradle = box(lx + 2 * (P.FIT + 2.5), ly + 2 * (P.FIT + 2.5), sv.min.Z + 14 - cradle_z0, cx, cy, cradle_z0)
    cradle -= box(lx + 2 * P.FIT, ly + 2 * P.FIT, 40, cx, cy, sv.min.Z)
    cradle -= box(lx - 6, 12, 60, cx, cy, cradle_z0 - 1)                     # let the cables past
    bowl += cradle & (Pos(0, 0, c) * Sphere(P.BALL_R - 0.5))
    # cap screws: 3 inserts in bosses at the split
    for a in (0, 120, 240):                      # clear of the hubs on +/-Y
        r = P.BALL_R - P.BALL_WALL - 4
        x, y = r * math.cos(math.radians(a)), r * math.sin(math.radians(a))
        boss = cyl(4, 10, x, y, split_z - 10) & (Pos(0, 0, c) * Sphere(P.BALL_R - 0.5))
        bowl += boss
        bowl -= insert_hole(x, y, split_z)
    # tilt hard stops: two lugs on the outside of the ball beside the -Y hub. The finger on the head
    # frame's -Y plate (pointing up at tilt 0) hits one at TILT_STOP_MAX and the other at TILT_STOP_MIN.
    fh = finger_half_angle()
    for a0, a1 in ((P.TILT_STOP_MAX + fh, P.TILT_STOP_MAX + fh + LUG_SPAN), (P.TILT_STOP_MIN - fh - LUG_SPAN, P.TILT_STOP_MIN - fh)):
        bowl += stop_lug(a0, a1) & box(200, 200, 200, z0=c - 60) - box(200, 200, 200, z0=split_z)
    return bowl


STOP_R0, STOP_R1 = 7.0, 13.5            # radial band of the tilt-stop finger and lugs (around the -Y hub)
FINGER_W = 6.0                          # REVIEW-2 #5: was 3 mm on the hub; now 6 mm on the frame plate
LUG_SPAN = 30.0                         # degrees: ~6 mm of lug at mid-radius


def finger_half_angle():
    return math.degrees(FINGER_W / 2 / ((STOP_R0 + STOP_R1) / 2))


def stop_sector(a0, a1, r0, r1, y0, y1):
    """Annular sector around the -Y tilt axis, between angles a0..a1 (deg from +Z, positive = towards -X,
    the way the finger swings when the head looks up), radii r0..r1, spanning |Y| y0..y1."""
    c = P.TILT_AXIS_Z
    pts = []
    for i in range(13):
        a = math.radians(a0 + (a1 - a0) * i / 12)
        pts.append((-r1 * math.sin(a), r1 * math.cos(a)))
    for i in range(13):
        a = math.radians(a1 - (a1 - a0) * i / 12)
        pts.append((-r0 * math.sin(a), r0 * math.cos(a)))
    face = make_face(Polyline(*[(x, -y0, c + z) for x, z in pts], close=True))
    return extrude(face, y1 - y0, dir=(0, -1, 0))


def stop_lug(a0, a1):
    c = P.TILT_AXIS_Z
    lug = stop_sector(a0, a1, STOP_R0, STOP_R1, P.BALL_R - 4, P.HEAD_FRAME_Y - 1.5)   # ends 1.5 short of the plate
    return lug - Pos(0, 0, c) * Sphere(P.BALL_R - P.BALL_WALL + 0.6)     # starts inside the wall (coincident faces break the union)


def ball_cap():
    c = P.TILT_AXIS_Z
    split_z = c + P.BALL_SPLIT_DZ
    cap = (Pos(0, 0, c) * Sphere(P.BALL_R) - Pos(0, 0, c) * Sphere(P.BALL_R - P.BALL_WALL))
    cap = cap & box(200, 200, 200, z0=split_z)
    for a in (0, 120, 240):                      # clear of the hubs on +/-Y
        r = P.BALL_R - P.BALL_WALL - 4
        x, y = r * math.cos(math.radians(a)), r * math.sin(math.radians(a))
        cap += cyl(4, 4, x, y, split_z) & (Pos(0, 0, c) * Sphere(P.BALL_R - 0.5))
        cap -= cyl(P.M3_CLEAR / 2, 30, x, y, split_z - 1)
    # cable exit at the top: the bundle loops up from here into the head (it only has to flex with tilt)
    cap -= cyl(P.CABLE_EXIT_D / 2, 20, z0=c + P.BALL_R - 10)
    return cap


def pan_gear():
    g = Pos(0, 0, GEAR_Z0) * involute_gear(P.GEAR_TEETH, P.GEAR_MODULE, P.GEAR_T, bore=P.POST_BORE)
    for loc in PolarLocations(P.POST_R - 4.5, 3, 0):
        p = loc.position
        g -= cyl(P.M3_CLEAR / 2, P.GEAR_T + 2, p.X, p.Y, GEAR_Z0 - 1)
        g -= cyl(P.M3_HEAD_D / 2 + 0.3, 3, p.X, p.Y, GEAR_Z0 - 0.01)        # heads recessed underneath
    return g


CLUTCH_SPIGOT_R = 11.0


def pinion_gear():
    """Rides free on the clutch hub's spigot, clamped between the hub flange and the cap by an M3 +
    wave washer: it slips (~0.3 N·m, set by the screw) before a child's twist can strip anything."""
    g = Pos(P.PAN_SERVO_X, 0, GEAR_Z0) * Rot(0, 0, 180 / P.GEAR_TEETH) * involute_gear(P.GEAR_TEETH, P.GEAR_MODULE, P.GEAR_T)
    g -= cyl(CLUTCH_SPIGOT_R + P.FIT, P.GEAR_T + 2, P.PAN_SERVO_X, 0, GEAR_Z0 - 1)
    return g


def clutch_hub():
    x = P.PAN_SERVO_X
    z_f = GEAR_Z0 - CLUTCH_FLANGE_T
    h = cyl(15, CLUTCH_FLANGE_T, x, 0, z_f) + cyl(CLUTCH_SPIGOT_R, P.GEAR_T - 0.3, x, 0, GEAR_Z0)   # spigot 0.3 short: cap clamps the gear
    for loc in PolarLocations(P.HORN_HOLE_R, 4, 45):
        p = loc.position
        h -= cyl(P.HORN_SCREW_CLEAR / 2, 20, x + p.X, p.Y, z_f - 1)
        h -= cyl(2.6, 20, x + p.X, p.Y, z_f + 2.0)                              # screw heads down in the spigot
    h -= cyl(3.2, 1.6, x, 0, z_f - 0.01)                                         # horn centre-screw head relief
    h -= insert_hole(x, 0, GEAR_Z0 + P.GEAR_T - 0.3, 6)
    return h


def clutch_cap():
    x = P.PAN_SERVO_X
    c_ = cyl(15, 2.0, x, 0, GEAR_TOP_Z) - cyl(P.M3_CLEAR / 2, 4, x, 0, GEAR_TOP_Z - 1)
    return c_


# ---------------------------------------------------------------- head
def head_outer(inset=0.0):
    b = Pos(P.HEAD_CX, 0, P.HEAD_CZ) * Box(P.HEAD_D - 2 * inset, P.HEAD_W - 2 * inset, P.HEAD_H - 2 * inset)
    return fillet(b.edges(), P.HEAD_FILLET - inset)


def head_underside_cut():
    """Concave underside: the head meets the clearance sphere at HEAD_HOLE_POLAR, then flares out."""
    c = P.TILT_AXIS_Z
    pol = math.radians(P.HEAD_HOLE_POLAR)
    r1, z1 = P.HEAD_CLEAR_R * math.sin(pol), -P.HEAD_CLEAR_R * math.cos(pol)
    zb = P.HEAD_CZ - P.HEAD_H / 2 - c
    r2 = r1 + (z1 - zb) / math.tan(math.radians(P.HEAD_FLARE_DEG))
    cut = revolve_profile([(0, z1), (r1, z1), (r2, zb), (r2 + 40, zb - 0.01), (r2 + 40, zb - 40), (0, zb - 40)], cz=c)
    return cut, (r1, z1, r2, zb)


def head_inside(margin=0.5):
    """The free volume inside the head: inside the walls, above the underside flare, outside the
    ball-clearance sphere. Everything mounted in the head is trimmed to this."""
    c = P.TILT_AXIS_Z
    inside = head_outer(P.HEAD_WALL + margin)
    _, (r1, z1, r2, zb) = head_underside_cut()
    t = P.HEAD_WALL / math.cos(math.radians(P.HEAD_FLARE_DEG)) + margin
    below = revolve_profile([(0, z1 + t), (r1, z1 + t), (r2, zb + t), (r2 + 60, zb + t), (r2 + 60, zb - 60), (0, zb - 60)], cz=c)
    return inside - below - Pos(0, 0, c) * Sphere(P.HEAD_CLEAR_R + margin)


FRAME_SCREW_XZ = ((22.0, 28.0), (15.0, 52.0), (-15.0, 36.0))   # (X, Z above the tilt axis): side-wall screws into frame tabs, clear of hub flange + ear servo
REAR_TOP_POSTS = ((-20.0, 54.0), (-20.0, -54.0))               # rear half screws down through its FLAT top into two posts (REVIEW-2 #1)


def head_shell():
    """The head shell, split front/back through the tilt axis. Assembly: frame over the ball, hubs in,
    then the two halves close round it from front and back and screw to the frame through the side walls."""
    shell = head_outer() - head_outer(P.HEAD_WALL)
    cut, (r1, z1, r2, zb) = head_underside_cut()
    c = P.TILT_AXIS_Z
    t = P.HEAD_WALL / math.cos(math.radians(P.HEAD_FLARE_DEG))
    flare = revolve_profile([(r1, z1), (r2, zb), (r2, zb + t), (r1, z1 + t)], cz=c)
    flare = flare & head_outer()
    shell = shell - cut + flare
    shell -= Pos(0, 0, c) * Sphere(P.HEAD_CLEAR_R)
    for s in (1, -1):                                       # hub passages (hubs are head-fixed: the gap never moves)
        shell -= cyl_y(P.HUB_D / 2 + P.FIT, 25, y0=(P.BALL_R - 6) if s > 0 else -(P.BALL_R - 6) - 25, z=c)
    for s in (1, -1):
        shell -= cyl_y(3.5, 10, x=P.EAR_X, y0=s * (P.HEAD_W / 2) - 5, z=P.EAR_Z)        # ear servo shafts
        for x, dz in FRAME_SCREW_XZ:                                                  # countersunk M3 into the frame tabs
            shell -= cyl_y(P.M3_CLEAR / 2, 10, x=x, y0=s * (P.HEAD_W / 2) - 5, z=c + dz)
            cs = Pos(x, s * (P.HEAD_W / 2 + 0.01), c + dz) * Rot(90 if s > 0 else -90, 0, 0) * Cone(3.2, 1.6, 1.6, align=C)
            shell -= cs
    for px, py in REAR_TOP_POSTS:                                # rear half screws down into the bridge posts
        shell -= cyl(P.M3_CLEAR / 2, 10, px, py, P.HEAD_CZ + P.HEAD_H / 2 - 5)
        shell -= Pos(px, py, P.HEAD_CZ + P.HEAD_H / 2 + 0.01) * Rot(180, 0, 0) * Cone(3.2, 1.6, 1.6, align=C)   # countersink
    # mic grille on top: Ø3 holes in rings out to r 40 (the XVF3800's mics sit near its Ø100 edge)
    top_z = P.HEAD_CZ + P.HEAD_H / 2
    for r, n in ((0, 1), (8, 6), (16, 12), (24, 18), (32, 24), (40, 30)):
        for loc in PolarLocations(r, n, 0) if r else [Pos(0, 0, 0)]:
            p = loc.position
            shell -= cyl(1.5, 30, XVF_X + p.X, p.Y, top_z - 26)
    rear = split(shell, Plane.YZ.offset(P.HEAD_SPLIT_X), keep=Keep.BOTTOM)
    front = split(shell, Plane.YZ.offset(P.HEAD_SPLIT_X), keep=Keep.TOP)
    for s in (1, -1):                                       # the rear half slides forward past the ear shafts: notch to its edge
        rear -= box(abs(P.EAR_X) + 1.0, 8, 7.4, P.EAR_X / 2 + 0.5, s * (P.HEAD_W / 2 - 1), P.EAR_Z - 3.7)
    return rear, front


def head_front(face):
    ez = P.HEAD_CZ + P.EYE_DZ
    fx = P.HEAD_CX + P.HEAD_D / 2
    for s in (1, -1):
        face -= cyl_x(P.EYE_WINDOW_D / 2, 20, x0=fx - 10, y=s * P.EYE_Y, z=ez)
        # display seat: shallow counterbore for the clear window disc, then the LCD clamp ring bosses
        face -= cyl_x(P.EYE_WINDOW_D / 2 + 2, 1.0, x0=fx - P.HEAD_WALL - 0.01, y=s * P.EYE_Y, z=ez)
        for dy, dz in eye_boss_offsets(s):
            boss_len = P.LCD_DEPTH
            face += cyl_x(3.5, boss_len, x0=fx - P.HEAD_WALL - boss_len, y=s * P.EYE_Y + dy, z=ez + dz)
            face -= cyl_x(1.6, boss_len, x0=fx - P.HEAD_WALL - boss_len - 0.5, y=s * P.EYE_Y + dy, z=ez + dz)  # M2 insert (Ø3.2) or self-tap
    # camera between the eyes: conical so a 120 deg lens ~4.5 mm back isn't vignetted
    cz = P.HEAD_CZ + P.CAM_DZ
    cone = Pos(fx - P.HEAD_WALL - 0.01, 0, cz) * Rot(0, 90, 0) * Cone(P.CAM_HOLE_IN / 2, P.CAM_HOLE_OUT / 2, P.HEAD_WALL + 0.02, align=C)
    face -= cone
    # shutter rails: the shutter slides DOWN to open (it sits over the hole when shut)
    rail_z0, rail_h = cz - P.SHUTTER_H / 2 - 16 - 2, P.SHUTTER_H + 16 + 4
    for s in (1, -1):
        rail = box(3.0, 2.0, rail_h, fx - P.HEAD_WALL - 1.5, s * (P.SHUTTER_W / 2 + P.FIT + 1.0), rail_z0)
        lip = box(1.6, 2.0 + 1.6, rail_h, fx - P.HEAD_WALL - 3.0 - 0.8, s * (P.SHUTTER_W / 2 + P.FIT + 1.0 - 0.8), rail_z0)
        face += rail + lip
    # head-height forward ToF window (sees table edges and benchtops the lidar can't)
    face -= cyl_x(5.0, 20, x0=fx - 10, z=P.HEAD_CZ + P.HEAD_TOF_DZ)
    for d in (-P.POLOLU_TOF_HOLES / 2, P.POLOLU_TOF_HOLES / 2):
        face += cyl_x(2.5, 4, x0=fx - P.HEAD_WALL - 4, y=d, z=P.HEAD_CZ + P.HEAD_TOF_DZ - 7)
        face -= cyl_x(0.9, 5, x0=fx - P.HEAD_WALL - 4.5, y=d, z=P.HEAD_CZ + P.HEAD_TOF_DZ - 7)
    return face


def eye_boss_offsets(s):
    """The face's 3 clamp bosses round each eye: top, outer, and low-outer. Nothing inboard (the camera
    lives there) and nothing straight below (the DualEye's 14-pin header and its cable exit there)."""
    r = P.LCD_PCB_D / 2 + 4
    d = r / math.sqrt(2)
    return [(0.0, r), (s * r, 0.0), (s * d, -d)]


def eye_holes(s):
    """The DualEye's 2 x M2 per eye, relative to the eye centre (dy, dz); s = +1 left eye, -1 right."""
    (i_dy, i_dz), (o_dy, o_dz) = P.EYE_HOLE_IN, P.EYE_HOLE_OUT
    return [(-s * i_dy, i_dz), (s * o_dy, o_dz)]


def eye_backplate(side):
    """Clamps one half of the split Waveshare DualEye against its window: 2 x M2 into the board's
    standoffs, 3 x M2 into inserts in the face's bosses. A ring, so the board's parts stay uncovered."""
    s = 1 if side == "L" else -1
    ez = P.HEAD_CZ + P.EYE_DZ
    fx = P.HEAD_CX + P.HEAD_D / 2
    ey = s * P.EYE_Y
    x0 = fx - P.HEAD_WALL - P.LCD_DEPTH - 2.0      # plate sits on the board's standoff ends and the boss ends
    plate = cyl_x(P.LCD_PCB_D / 2 + 8, 2.0, x0=x0, y=ey, z=ez)
    plate -= cyl_x(11.0, 4, x0=x0 - 1, y=ey, z=ez)                       # open middle: ESP32, SD slot, FFC connector
    for dy, dz in eye_holes(s) + eye_boss_offsets(s):
        plate -= cyl_x(P.M2_CLEAR / 2, 4, x0=x0 - 1, y=ey + dy, z=ez + dz)
    inner_edge = P.EYE_Y - P.LCD_PCB_D / 2 + 1.0
    plate -= box(10, 60, 80, x0, s * (inner_edge - 30), ez - 40)          # nothing inboard: the camera lives there
    plate -= box(10, 20, 15, x0, ey, ez - 26)                             # 14-pin header + its cable, straight down
    return plate


def shutter():
    cz = P.HEAD_CZ + P.CAM_DZ
    fx = P.HEAD_CX + P.HEAD_D / 2
    s = box(1.6, P.SHUTTER_W, P.SHUTTER_H, fx - P.HEAD_WALL - 1.6 / 2 - P.FIT, 0, cz - P.SHUTTER_H / 2)
    s += box(3, 6, 5, fx - P.HEAD_WALL - P.FIT - 1.6 - 1.0, 0, cz - P.SHUTTER_H / 2 - 4)  # push-rod lug, 0.5 mm into the plate
    s -= cyl_x(0.9, 10, x0=fx - 10, z=cz - P.SHUTTER_H / 2 - 2)
    return s


def head_frame():
    """U frame inside the head: side plates carry the hubs, ear servos and boards; the top bridge carries
    the mic array. Both head halves screw to it. The plates stop FRAME_TRIM_DZ below the tilt axis so the
    head halves' underside can slide past them (REVIEW-2 #1). The -Y plate carries the tilt-stop finger."""
    c = P.TILT_AXIS_Z
    fy = P.HEAD_FRAME_Y
    frame = Part()
    for s in (1, -1):
        z_lo = c + P.FRAME_TRIM_DZ
        plate = box(76, 4, c + 72 - z_lo, -4, s * (fy + 2), z_lo)
        plate = fillet(plate.edges().filter_by(Axis.Y), 6)
        frame += plate
        for a in FLANGE_SCREW_ANGLES:                        # bosses for the hub flange inserts, on the inside
            bx, bz = P.HUB_FLANGE_SCREW_R * math.cos(math.radians(a)), P.HUB_FLANGE_SCREW_R * math.sin(math.radians(a))
            frame += cyl_y(3.6, 5, x=bx, y0=s * fy - (5 if s > 0 else 0), z=c + bz)
        frame -= cyl_y(P.FRAME_HUB_HOLE_R, 12, y0=s * fy - 6, z=c)
        for a in FLANGE_SCREW_ANGLES:
            bx, bz = P.HUB_FLANGE_SCREW_R * math.cos(math.radians(a)), P.HUB_FLANGE_SCREW_R * math.sin(math.radians(a))
            frame -= cyl_y(P.M3_INSERT_D / 2, 7, x=bx, y0=s * (fy + 4) - (7 if s > 0 else 0), z=c + bz)
        # ear servo shelf on the outside of the plate
        frame += box(P.MICRO_L + 8, P.MICRO_SHAFT_LEN - 4, 4, P.EAR_X, s * (fy + 4 + (P.MICRO_SHAFT_LEN - 4) / 2), P.EAR_Z + P.MICRO_W / 2 + P.FIT)
        # tabs out to the side walls; the head halves screw into them (inserts at the outer ends)
        for x, dz in FRAME_SCREW_XZ:
            y_wall = P.HEAD_W / 2 - P.HEAD_WALL - 0.3
            frame += box(9, y_wall - (fy + 4), 9, x, s * (fy + 4 + (y_wall - fy - 4) / 2), c + dz - 4.5)
            frame -= cyl_y(P.M3_INSERT_D / 2, 7, x=x, y0=s * y_wall - (7 if s > 0 else 0), z=c + dz)
    # the tilt-stop finger: on the -Y plate's inner face, pointing up at tilt 0, meeting the ball's lugs
    fh = finger_half_angle()
    frame += stop_sector(-fh, fh, STOP_R0, STOP_R1 + 3.0, P.HEAD_FRAME_Y - 5.5, P.HEAD_FRAME_Y + 0.5)   # 4 mm overlap with the lugs
    top_z = c + P.HEAD_CLEAR_R + 2
    bridge = box(80, 2 * (fy + 4), 4, XVF_X - 2, 0, top_z)              # front edge stops short of the camera
    post_top = P.HEAD_CZ + P.HEAD_H / 2 - P.HEAD_WALL - 0.3
    for px, py in REAR_TOP_POSTS:                                        # posts up to the flat top of the rear half
        bridge += cyl(4.5, post_top - top_z, px, py, top_z)
        bridge -= insert_hole(px, py, post_top)
    bridge -= cyl(28, 10, XVF_X, 0, top_z - 1)                               # lighten + cable pass from the ball's top
    frame += bridge
    for dx in (-P.XVF_HOLES / 2, P.XVF_HOLES / 2):
        for dy in (-P.XVF_HOLES / 2, P.XVF_HOLES / 2):
            post_h = XVF_Z0 - (top_z + 4)
            frame += cyl(3.2, post_h, XVF_X + dx, dy, top_z + 4)
            frame -= cyl(1.1, 8, XVF_X + dx, dy, XVF_Z0 - 7.5)                # M2.5 self-tap (hole size UNCONFIRMED)
    # face ESP32-S3 + USB hub mount on the OUTER faces of the side plates (M2 bosses), behind the ears
    for s in (1, -1):
        for dx, dz in ((-42, 16), (-42, 42), (-30, 30), (-30, 42)):      # clear of the hub flange and tabs
            frame += cyl_y(2.6, 4, x=dx, y0=s * (fy + 4) - (4 if s < 0 else 0), z=c + dz)
            frame -= cyl_y(0.9, 6, x=dx, y0=s * (fy + 4) - (5 if s < 0 else 1), z=c + dz)
    return frame & head_inside()


FLANGE_SCREW_ANGLES = (30.0, 150.0)          # upper half only (the flanges are trimmed below)


def tilt_adapter():
    """Screwed to the tilt horn INSIDE the ball before the cap goes on (4 x M2.5)."""
    c = P.TILT_AXIS_Z
    y0 = TILT_HORN_Y
    a = cyl_y(TILT_CLUTCH_R, TILT_ADAPTER_T, y0=y0, z=c)
    for loc in PolarLocations(P.HORN_HOLE_R, 4, 45):
        p = loc.position
        a -= cyl_y(P.HORN_SCREW_CLEAR / 2, 10, x=p.X, y0=y0 - 1, z=c + p.Y)
        a -= cyl_y(2.4, 10, x=p.X, y0=y0 + 3.0, z=c + p.Y)                    # heads recessed
    a -= cyl_y(3.2, 1.6, y0=y0 - 0.01, z=c)                                   # horn centre-screw head relief
    a -= cyl_y(P.M3_INSERT_D / 2, TILT_ADAPTER_T + 1, y0=y0 + 1.6, z=c)       # insert for the clutch screw
    return a


TILT_ADAPTER_T = 6.0
TILT_CLUTCH_R = 12.5                     # friction faces at up to r 12.5 (was r ~6): ~4x the holding torque
# The clutch screw is a D4 x M3 shoulder screw (4 or 6 mm shoulder, both bought). The shoulder runs
# through the coupler's floor and bottoms on the adapter, so the Belleville stack under its head always
# gets the same squeeze. Stack: 8 x 4.2 discs in 0.2 / 0.3 / 0.4 (60 bought), mixed to tune the slip.
TILT_FLOOR = 2.0                         # coupler floor = the friction disc between adapter and stack
SHOULDER_MAX = 6.0                       # room for the longer screw; the 4 mm one leaves 2 mm spare
SHOULDER_HEAD_H = 3.0                    # D4 x M3 head height. UNCONFIRMED: measure (head is ~Ø7)
SHOULDER_D = 4.2                         # through the floor: the coupler turns on the 4 mm shoulder
HUB_HEX_AF = 9.0                         # was 7: the 8 mm discs must fit inside the hex socket
HEX_ENGAGE = 5.0
TILT_COUPLER_T = SHOULDER_MAX + SHOULDER_HEAD_H + 0.5 + HEX_ENGAGE   # 14.5; ends 1.3 inside the ball wall


def tilt_coupler():
    """Friction clutch for tilt (REVIEW-2 #4): turns on an M3 shoulder into the adapter, pressed onto the
    adapter's face by a Belleville stack under the screw head. The drive hub's hex end keys into its socket.
    Slips at ~0.7 N·m (holds the head up, gives way to a child's twist)."""
    c = P.TILT_AXIS_Z
    y0 = TILT_HORN_Y + TILT_ADAPTER_T
    cp = cyl_y(TILT_CLUTCH_R, TILT_COUPLER_T, y0=y0, z=c)
    cp -= cyl_y(SHOULDER_D / 2, TILT_COUPLER_T + 2, y0=y0 - 1, z=c)
    hex_r = HUB_HEX_AF / 2 / math.cos(math.radians(30)) + P.FIT
    sock = make_face(Polyline(*[(hex_r * math.cos(math.radians(60 * i)), y0 + TILT_FLOOR, c + hex_r * math.sin(math.radians(60 * i))) for i in range(6)], close=True))
    cp -= extrude(sock, TILT_COUPLER_T, dir=(0, 1, 0))                         # hex socket; Belleville stack + screw head sit at its floor
    return cp


def hubs():
    c = P.TILT_AXIS_Z
    fy = P.HEAD_FRAME_Y
    inside = head_inside(0.3)
    flange_t = 4.0
    trim = box(200, 200, 200, z0=c + P.FLANGE_TRIM_DZ)                 # flat bottom: the halves' underside slides under it
    # +Y: drive hub. Hex end keys into the tilt coupler; the flange screws to the frame plate.
    y_hex = TILT_HORN_Y + TILT_ADAPTER_T + SHOULDER_MAX + SHOULDER_HEAD_H + 0.5   # clears the head of the 6 mm shoulder screw
    y_tube = TILT_HORN_Y + TILT_ADAPTER_T + TILT_COUPLER_T + 0.5
    hex_r = HUB_HEX_AF / 2 / math.cos(math.radians(30))
    hx = make_face(Polyline(*[(hex_r * math.cos(math.radians(60 * i)), y_hex, c + hex_r * math.sin(math.radians(60 * i))) for i in range(6)], close=True))
    drive = extrude(hx, y_tube - y_hex + 0.5, dir=(0, 1, 0))
    drive += cyl_y(P.HUB_D / 2, fy + 4 - y_tube, y0=y_tube, z=c)
    drive += cyl_y(P.HUB_FLANGE_R, flange_t, y0=fy + 4, z=c) & inside & trim
    # -Y: plain idle hub turning in the ball's bushing (no bore: cables now leave through the ball's top)
    idle = cyl_y(P.HUB_D / 2, (fy + 4) - (P.BALL_R - 8), y0=-(fy + 4), z=c)
    idle += cyl_y(P.HUB_FLANGE_R, flange_t, y0=-(fy + 4 + flange_t), z=c) & inside & trim
    for a in FLANGE_SCREW_ANGLES:
        bx, bz = P.HUB_FLANGE_SCREW_R * math.cos(math.radians(a)), P.HUB_FLANGE_SCREW_R * math.sin(math.radians(a))
        drive -= cyl_y(P.M3_CLEAR / 2, 12, x=bx, y0=fy + 4 - 6, z=c + bz)
        idle -= cyl_y(P.M3_CLEAR / 2, 12, x=bx, y0=-(fy + 4) - 6, z=c + bz)
    return drive, idle


def ear(side):
    s = 1 if side == "L" else -1
    y0 = s * (P.HEAD_W / 2 + 1.5)
    # paddle in the XZ plane: rounded leaf, 52 tall
    pts = [(0, 0)]
    for i in range(0, 181, 10):
        a = math.radians(i)
        pts.append((13 * math.cos(a), 8 + 44 * math.sin(a) ** 0.8))
    leaf = make_face(Polyline(*[(x, 0, z) for x, z in pts], close=True))
    e = extrude(leaf, 5.0, dir=(0, s, 0))
    e = Pos(P.EAR_X, y0, P.EAR_Z - 8) * e
    e += cyl_y(7, 5, x=P.EAR_X, y0=y0 if s > 0 else y0 - 5, z=P.EAR_Z)
    e -= cyl_y(2.4, 10, x=P.EAR_X, y0=y0 - 5, z=P.EAR_Z)                          # servo spline (press, then screw)
    return e


# ---------------------------------------------------------------- dock
def dock():
    w = P.DOCK_W
    base = box(140, w, 8, -P.SKIRT_R - 2 - 70, 0, 0)          # never under the robot: the caster would climb it
    # back wall shaped to the robot's skirt (robot reverses in)
    back = box(30, w, 46, -P.SKIRT_R - 15 - 1, 0, 0)
    back -= cyl(P.SKIRT_R + 1.0, 60, z0=-1)
    base += back
    for y in (-20, 20):
        base -= cyl_x(5, 20, x0=-P.SKIRT_R - 12, y=y, z=30)      # spring-contact pads sit in here
    base -= box(10, 60, 6, -P.SKIRT_R - 20, 0, 4)                  # wire channel
    # tower is taller than the bed: two halves joined by a glued-and-pinned tenon
    half = P.DOCK_TOWER_H / 2
    tx = -P.SKIRT_R - 25
    lower = box(16, 60, half, tx, 0, 46)
    lower -= box(8, 40, 20, tx, 0, 46 + half - 20)
    upper = box(16, 60, half, tx, 0, 46 + half)
    upper += box(8 - 2 * P.FIT, 40 - 2 * P.FIT, 20 - 0.5, tx, 0, 46 + half - 20 + 0.5)   # clearance on the tenon only
    tag_z0 = 46 + P.DOCK_TOWER_H - P.TAG_SIZE - 16
    upper += box(6, P.TAG_SIZE + 16, P.TAG_SIZE + 16, -P.SKIRT_R - 20, 0, tag_z0)
    upper -= box(2, P.TAG_SIZE + 0.6, P.TAG_SIZE + 0.6, -P.SKIRT_R - 16.5, 0, tag_z0 + 7.7)   # printed-paper tag recess
    return base, lower, upper


# ---------------------------------------------------------------- everything
def printed():
    p = {}
    p["chassis_plate"] = chassis_plate()
    p["bumper"], p["skirt_rear"] = skirt_shells()
    for side in ("L", "R"):
        p[f"wheel_hub_{side}"] = wheel_hub(side)
        p[f"tyre_{side}"] = tyre(side)
        p[f"ear_{side}"] = ear(side)
        p[f"eye_backplate_{side}"] = eye_backplate(side)
    p["caster_housing_F"], p["caster_retainer_F"] = caster_parts(True)
    p["caster_housing_R"], p["caster_retainer_R"] = caster_parts(False)
    p["waist_deck"] = waist_deck()
    p["body_floor"] = body_floor()
    p["body_front"], p["body_back"] = body_shells()
    p["screen_clamp"] = screen_clamp()
    p["body_lid"] = body_lid()
    p["ball_bowl"] = ball_bowl()
    p["ball_cap"] = ball_cap()
    p["pan_gear"] = pan_gear()
    p["pinion_gear"] = pinion_gear()
    p["clutch_hub"] = clutch_hub()
    p["clutch_cap"] = clutch_cap()
    p["tilt_adapter"] = tilt_adapter()
    p["tilt_coupler"] = tilt_coupler()
    rear, front = head_shell()
    p["head_rear"] = rear
    p["head_front"] = head_front(front)
    p["shutter"] = shutter()
    p["head_frame"] = head_frame()
    p["hub_drive"], p["hub_idle"] = hubs()
    p["dock_base"], p["dock_tower_lower"], p["dock_tower_upper"] = dock()
    return p
