"""Every dimension for Claude's body, in one place.

Frame: X forward, Y left, Z up, origin on the floor under the centre of the wheel axle. mm.
Bought-part sizes marked (UNCONFIRMED) must be checked against the real part before printing its
bracket. The big shells don't depend on them.
"""

# ---- print limits -------------------------------------------------------------------------
BED = 256.0            # Centauri Carbon build volume (cube)
BED_MARGIN = 8.0       # keep every part this far inside the bed
MIN_WALL = 1.6         # 4 perimeters at 0.4 nozzle
MIN_WEB = 1.2          # between holes (grille lesson, 2026-08-20)
FIT = 0.25             # clearance per side for a sliding fit (applied to ONE side only)
LOOSE = 0.5            # per side for big printed-on-printed fits (130 mm walls bow)

# ---- fasteners ----------------------------------------------------------------------------
M3_CLEAR = 3.4
M3_INSERT_D = 4.0      # hole for an M3x5.7 heat-set insert (Ruthex-style; UNCONFIRMED per brand)
M3_INSERT_DEPTH = 6.0
M3_HEAD_D = 6.0
M2_CLEAR = 2.4
M2_5_CLEAR = 2.9

# ---- base / skirt -------------------------------------------------------------------------
SKIRT_R = 118.0        # outer radius -> Ø236 footprint
SKIRT_WALL = 3.0
SKIRT_Z0 = 8.0         # floor clearance under the skirt (review S8: less room for toddler fingers; thresholds <= 6 mm)
SKIRT_Z1 = 104.0       # top of the skirt = underside of the waist deck
BUMPER_ARC = 200.0     # degrees of the front skirt that float as the bumper
BUMPER_TRAVEL = 3.0    # how far it can move back before the switches stop it

CHASSIS_Z0 = 14.0
CHASSIS_T = 5.0
CHASSIS_R = SKIRT_R - SKIRT_WALL - LOOSE - 1.0   # inside the skirt with a real gap

STANDOFF_D = 14.0
STANDOFF_XY = [(30.0, 60.0), (30.0, -60.0), (-48.0, 62.0), (-48.0, -62.0)]

# ---- drive ----------------------------------------------------------------------------------
WHEEL_D = 100.0        # over the tyre
TYRE_T = 5.0           # TPU tyre radial thickness
WHEEL_W = 22.0
AXLE_Z = WHEEL_D / 2
WHEEL_Y = 86.0         # wheel centre-plane; track width = 2*WHEEL_Y
TRACK = 2 * WHEEL_Y
WELL_CLEAR = 3.0       # air round the wheel inside its well

# Feetech STS3215 (UNCONFIRMED until research lands; see vendor.py)
SERVO_L = 45.22        # Waveshare ST3215 drawing (2022-06-08)
SERVO_W = 24.72
SERVO_H = 35.0         # case, without horns
SERVO_SHAFT_FROM_END = 10.11  # shaft axis to the near end of the case
HORN_D = 19.2          # metal disc horn
HORN_T = 1.25          # horn face stands this far proud of the case top
IDLER_T = 1.05         # idler horn on the bottom face
HORN_HOLE_R = 7.0      # 4 x Ø2.5 on a 14 mm circle
HORN_SCREW_CLEAR = 2.9 # M2.5 (horn thread UNCONFIRMED: check the screw bag)

BEARING_OD, BEARING_ID, BEARING_W = 22.0, 8.0, 7.0   # 608ZZ

CASTER_BALL = 25.4     # loose 1" chrome steel ball in a printed housing
CASTER_X_FRONT = 78.0  # front ball, lifted (only touches when it pitches forward)
CASTER_X_REAR = 86.0   # rear ball, load-bearing
CASTER_FRONT_LIFT = 3.0

# ---- battery 3S2P 18650 -----------------------------------------------------------------
CELL_D, CELL_L = 18.6, 65.5
PACK_L = CELL_L + 6          # with nickel strip + wrap
PACK_W = 3 * CELL_D + 4
PACK_H = 2 * CELL_D + 4
PACK_X = -60.0               # on a shelf above the rear caster: centre of mass well behind the axle (review S5)
PACK_SHELF_Z = 35.0          # top of the battery shelf (rear caster housing tops out at ~28 mm)               # between the wheel servos, behind the axle, clear of the rear caster

# ---- waist + lidar ----------------------------------------------------------------------
DECK_Z0 = SKIRT_Z1
DECK_T = 4.0
DECK_R = SKIRT_R - 6.0
LIDAR_W, LIDAR_D, LIDAR_H = 46.29, 54.0, 35.0         # LDROBOT STL-19P / LD19 drawing (D x W as mounted: connector to the rear)
LIDAR_HOLE_FRONT_SPAN = 46.80                         # two front holes, Ø2.5
LIDAR_HOLE_BACK = 31.92                               # third hole, centred, this far behind them
LIDAR_SCAN_ABOVE_BASE = 35.0 - 7.8                    # laser plane is 7.8 below the turret top
BAND_Z0 = DECK_Z0 + DECK_T                            # open band starts at deck top
BAND_H = 40.0
PILLAR_W = 9.0
PILLAR_ANGLES = [180.0, 60.0, -60.0]                  # none dead-ahead
PILLAR_R = 62.0                  # inside the new abdomen's floor (was DECK_R - 8 under the cone)

# ---- body column (the abdomen) -------------------------------------------------------------
# 29 Oct: a rounded box (matches the head) instead of the old cone, with the 7" DSI screen on a front
# face leaning back SCREEN_TILT. Holds the Pi 5 + Freenove M.2 board, Coral, 2 case fans and the 2
# speaker drivers. Every bought-part size marked UNCONFIRMED is a placeholder until it's measured.
BODY_Z0 = BAND_Z0 + BAND_H        # floor plate under the column
BODY_FLOOR_T = 4.0
BODY_D0, BODY_W0, BODY_CR0 = 170.0, 220.0, 45.0   # bottom of the shell: depth (X), width (Y), corner radius
BODY_D1, BODY_W1, BODY_CR1 = 150.0, 200.0, 40.0   # top
BODY_H = 140.0                    # shell height (was 96 on the cone; the screen needs the height)
BODY_WALL = 2.4
BODY_Z1 = BODY_Z0 + BODY_FLOOR_T + BODY_H
SCREEN_TILT = 18.0                # screen face leans back this far from vertical (faces up at people)
FACET_X0 = 75.0                   # where the screen face meets the floor (10 mm behind the box front)
SCREEN_W, SCREEN_H, SCREEN_T = 165.0, 100.0, 8.0    # 7" DSI 800x480 outline + depth. UNCONFIRMED: measure
SCREEN_VIEW_W, SCREEN_VIEW_H = 156.0, 87.0          # window in the face (active area ~154 x 86). UNCONFIRMED
SCREEN_V0 = 14.0                  # screen's bottom edge, measured up the face from the floor
SCREEN_GLASS_IN = 1.2             # glass sits this far behind the face's outer surface
SPK_D, SPK_T = 60.0, 30.0         # Logitech Z200 driver: Ø + depth. UNCONFIRMED: measure
SPK_X, SPK_DZ = -10.0, 60.0       # side-firing, one each side; height above the shell bottom
FAN_S = 40.0                      # Freenove case fan size. UNCONFIRMED: measure (could be 30)
FAN_HIGH_DZ = 110.0               # one exhaust fan high on the back; cool air comes in through the floor
FAN_HIGH_Y = 40.0                 # off-centre: the pan gears are behind the middle of the back
FLOOR_INTAKE_XY = (25.0, -70.0)   # passive intake grille in the floor, beside the M.2 board
POCKET_W, POCKET_H, POCKET_D = 70.0, 45.0, 18.0
POCKET_DZ = 40.0                  # note pocket's bottom, above the shell bottom

# ---- neck + head --------------------------------------------------------------------------
# The head sits on a ball. Ball centre = tilt axis. Head material stays >= HEAD_CLEAR_R from the
# ball centre everywhere except the two hubs ON the tilt axis, so tilting can never close a gap on
# the ball. Pan: a hollow post turns in a 6806 bearing in the lid (constant gap, cables up the
# middle), driven by a 1:1 gear pair from a servo hidden under the lid.
NECK_GAP = 3.0
LID_T = 4.0
LID_TOP = BODY_Z1 + LID_T
PAN_BRG_OD, PAN_BRG_ID, PAN_BRG_W = 42.0, 30.0, 7.0    # 6806-2RS
POST_R = PAN_BRG_ID / 2
POST_BORE = 14.0                   # cable bundle: USB + 5 V pair + servo bus
COLLAR_R = 24.0
COLLAR_T = 3.0
COLLAR_Z0 = LID_TOP + NECK_GAP
POST_VISIBLE = 26.0                # bare post between collar and ball: keeps the back of the head >25 mm off the lid when looking up
BALL_R = 46.0
BALL_WALL = 2.4
import math as _m
TILT_AXIS_Z = COLLAR_Z0 + COLLAR_T + POST_VISIBLE + _m.sqrt(BALL_R**2 - POST_R**2)
BALL_SPLIT_DZ = 14.0               # bowl/cap split above the axis
BALL_HOLE_D = 14.0                 # where the hubs enter, on the tilt axis
HUB_D = 10.0                       # thin enough that the head's underside never touches it as the halves slide in (REVIEW-2 #1)
CABLE_EXIT_D = 18.0                # cables leave the ball through its top, then loop up into the head (flexes with tilt)
HEAD_CLEAR_R = BALL_R + NECK_GAP   # no head material inside this sphere (except hubs)
HEAD_HOLE_POLAR = 80.0             # deg from straight down where the head's underside meets that sphere
GEAR_MODULE, GEAR_TEETH, GEAR_T = 1.5, 30, 10.0   # was m1 x 6 mm: ~2.5x tooth strength (review S3), plus a slip clutch
GEAR_CD = GEAR_MODULE * GEAR_TEETH # centre distance for a 1:1 pair
PAN_SERVO_X = -GEAR_CD
HEAD_W, HEAD_H, HEAD_D = 170.0, 120.0, 118.0
HEAD_CZ = TILT_AXIS_Z + 30.0       # head centre sits above the tilt axis
HEAD_CX = 6.0
HEAD_WALL = 2.0                    # 5 perimeters; was 2.4 (the head is the heaviest thing up high)
HEAD_FILLET = 30.0
HEAD_FRAME_Y = 55.0                # inner face of the head frame side plates (>= HEAD_CLEAR_R)
EYE_Y = 38.0
EYE_DZ = 10.0                      # above head centre
EYE_WINDOW_D = 34.0                # Waveshare 1.28in: visible Ø32.4, glass Ø35.5
# Eyes = Waveshare ESP32-S3-DualEye-LCD-1.28 (SKU 32267), split in two and joined by its 200 mm 18-pin FFC.
# From Waveshare's drawing (Touch version; assumed the same outline): 93.5 x 36.5 whole, each eye Ø36.5.
LCD_PCB_D = 36.5
LCD_GLASS_D = 35.5
# 2 x M2 per eye, diagonal, relative to that eye's centre: (towards the middle, up) and (outwards, down).
EYE_HOLE_IN = (10.4, 11.36)        # eye centre 93.5/2 - 36.5/2 = 28.5 from the middle; hole at 18.10: 10.4 in, 11.36 up
EYE_HOLE_OUT = (10.5, -11.29)      # hole at 39.00: 10.5 out, 11.29 down
LCD_DEPTH = 6.1                    # glass front to the M2 standoff ends. UNCONFIRMED for the DualEye: measure on arrival
CAM_DZ = EYE_DZ                     # camera between the eyes ("third eye"): the only spot outside the ball-clear sphere
FACE_DEPTH = 22.0                  # front cap of the head is a separate print (charcoal)
SHUTTER_W, SHUTTER_H = 20.0, 18.0  # orange camera shutter; slides DOWN 16 mm to open
CAM_HOLE_IN, CAM_HOLE_OUT = 14.0, 23.0   # conical: a 120 deg lens ~4.5 mm back doesn't vignette                   # face plate sits this far back from the shell lip
EAR_X, EAR_Z = -6.0, None           # ear pivots on the upper sides of the head (set below)
MICRO_L, MICRO_W, MICRO_SHAFT_LEN = 23.0, 12.5, 28.0   # MG90S envelope (UNCONFIRMED)
HEAD_FLARE_DEG = 36.0              # underside flare angle from horizontal
TILT_MIN, TILT_MAX = -15.0, 30.0   # software range, everywhere (review B4)
TILT_STOP_MIN, TILT_STOP_MAX = -16.0, 31.0   # hard mechanical stops (finger on the idle hub vs lugs on the ball)
PAN_LIMIT = 150.0                  # hollow post: no slot to run out of, limit is cable twist

# ---- dock -----------------------------------------------------------------------------------
DOCK_W = 150.0
DOCK_TOWER_H = 300.0
TAG_SIZE = 80.0

EAR_Z = HEAD_CZ + 26.0

# ---- sensors -----------------------------------------------------------------------------
TOF_MIN_RANGE = 40.0               # VL53L1X is inaccurate below 40 mm
DROP_TOF_Z = 52.0                  # down-looking drop sensors sit this high (>= TOF_MIN_RANGE + margin)
DROP_TOF_POS = ((100.0, 27.0), (95.0, 145.0), (100.0, -27.0))   # (radius, angle) [left, REAR, right]
# front ones sit 89 mm ahead of the wheels: e-stop at 1.5 m/s2 from 0.25 m/s = 21 mm + ~25 mm latency (review B1)
ESTOP_DECEL = 1.5
V_MAX = 0.25
STOP_LATENCY_S = 0.10
FWD_TOF_Z = 32.0
FWD_TOF_ANGLES = (26.0, -26.0)
FWD_TOF_SETBACK = 45.0             # sensor face this far behind the bumper face
POLOLU_TOF_HOLES = 12.7            # 2 x M2
BUMPER_TAB_ANGLES = (-55.0, -15.0, 15.0, 55.0)   # clear of the wheel wells (56..124 deg), front caster and drop towers
BUMPER_SWITCH_ANGLES = (-42.0, 42.0)
BUMPER_SLOT_SIDE = 0.5        # per-side play across a slot: all four slots run parallel to X so the ring can slide back
XVF_D = 100.0                      # reSpeaker XVF3800 round board
XVF_HOLES = 66.0                   # 4 holes on a 66 x 66 square

HEAD_TOF_DZ = -25.0                # forward VL53L1X window under the shutter's open position (sees table edges at head height)
FRAME_TRIM_DZ = -9.0               # frame plates stop 9 mm below the tilt axis (the underside cone peaks at -10.4)
FLANGE_TRIM_DZ = -12.0             # hub flanges stop at -12 (cone peaks at -13.3 at their radius)
HEAD_SPLIT_X = 0.0                 # head splits front/back THROUGH the tilt axis: frame + hubs go on first, halves close round them
HUB_FLANGE_R = 23.0
HUB_FLANGE_SCREW_R = 19.5
FRAME_HUB_HOLE_R = 5.5
BODY_BOSS_ANGLES = (30.0, 70.0, 150.0, 210.0, 290.0, 330.0)   # none on the X=0 split (review S9), clear of window + pocket
AXLE_PIN_D, AXLE_PIN_L = 8.0, 30.0  # steel dowel / cut M8 bolt instead of a printed stub (review)
