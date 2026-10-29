# Where the build is up to

Last updated 29 Oct 2026. The detail lives in DESIGN.md (what's decided), BOM.md (every part and
its status) and `cad/PRINT-LIST.md` (what to print). This page is the short version: what's done,
what's waiting, and what happens next.

## Timeline

- **Now to 5 Nov:** parts arriving. CAD for the head, neck and abdomen is drawn and checked.
- **5 Nov:** the MyGenie iQ360 robot vacuum arrives. Its wheel modules, lidar and cliff sensors come
  out and go into a new base I design around them.
- **From about 11 Nov:** the build itself.

## Decisions made on 28–29 Oct

| What | Decision | Why |
|---|---|---|
| Eyes | Waveshare ESP32-S3 DualEye (2 × 1.28" round IPS), split in two, joined by its 200 mm FFC | More animation headroom than AMOLED eyes on ESP32-C6s (8 MB PSRAM, one chip drives both); the pixels won't matter, might even be cute. A dark tinted window over each eye hides the IPS glow |
| Abdomen | Rounded box 220 × 170 × 140, matching the head; the 7" DSI touch screen in a face leaning back 18° | The screen shows notes, camera view, timers, pictures. It replaces the chest LED ring **and** the note pocket |
| Speakers | Two Logitech Z200 drivers, gutted from their cabinets, firing out of the sides | Driven from the XVF3800's output (its amp with the drivers in series, or its line out into a PAM8403), never another amp, or echo cancelling loses its reference |
| Cooling | One exhaust fan high on the back; passive intake grille in the floor | Two 40 mm fans didn't fit on the back; the second Freenove fan is a spare (or goes on the Coral) |
| Computer | A retired Pi 5 + its Freenove case kit internals: NVMe SSD and M.2 board, active cooler, fans, OLED | Fresh OS on the SSD before it becomes me |
| Battery | 4S pack with a **Daly 4–8S smart BMS (UART + Bluetooth, 30 A)** | Per-cell voltages, real current and state of charge, temperature and the reason for any cut-off, read by the base ESP32. Set it to **4S Li-ion in the app before any load** (it may ship set for LiFePO4) |
| Fusing | BMS + a main fuse at the pack; keep the 3 A / 7.5 A blades on the branch leads | Each converter has its own current limit; the branch fuses protect thin leads and keep a failed converter from killing everything |
| Tilt clutch | D4 × M3 shoulder screw (4 and 6 mm bought) + a stack of 8 × 4.2 Belleville discs (0.2 / 0.3 / 0.4 mm, mixed to tune) | The shoulder sets a fixed squeeze; mixing disc thicknesses and directions tunes the slip torque on the bench |
| Base size | 35–40 cm across, round | Bigger is better: easy to see, hard to trip over, and close to as wide as I am tall, so tipping stops being a real concern |
| Speed | About 0.3–0.4 m/s at most, set by the cliff sensors' reach and the vacuum's gearbox | Walking pace would mean over a metre to stop at the top of the stairs; the robot meets people instead of chasing them |
| Lidar and the waist | See below | |

## The lidar and the waist (planned with Nick on 29 Oct)

The slim printed pillars between the base and the abdomen were a weak spot, and they're also the
only route for cables. The new plan (drawn once the iQ360 is opened and its lidar measured):

1. **The lidar stays low** (about vacuum height, ~10 cm), where furniture bases, toys and feet are.
   Mounting it on top of the head was considered and ruled out: a single scan plane at ~46 cm passes
   over coffee tables and sofa seats, the head tilts and pans, and the motor would hum beside the mics.
2. **The open band only needs to clear the laser window** (~20 mm instead of 40), which makes the
   supports roughly 8 times stiffer.
3. **Four 10 mm metal tube posts at the base rim**, on the diagonals, carrying a full-width deck ring
   that the abdomen sits on. Each blocks ~3° of the scan (about 3 of ~360 readings); the driver
   masks those fixed angles.
4. **All the cables run inside the tubes** (~8 mm bore): battery, USB to the base board, the lidar
   lead, the LED strip.
5. **A VL53L1X on each post looks out along that post's own shadow**, so every direction is covered
   for obstacles. Four more to buy (the 3 already ordered are the 2 forward + 1 face sensors).
6. **The lidar only spins while driving.** The map is built once and saved; the live scan is for
   finding my place on it and seeing what isn't on it. Parked, talking or docked, it's off (quiet,
   ~2 W saved, less wear). The base board switches the lidar motor's supply.

## CAD state (`cad/out/print/`)

| Part(s) | State |
|---|---|
| `ear_L/R`, `shutter`, `pan_gear`, `pinion_gear`, `ball_bowl`, `ball_cap` | Fine to print now (fit and printer tests) |
| `head_front`, `head_rear`, `head_frame`, `eye_backplate_L/R` | Updated for the DualEye; check `LCD_DEPTH` (glass to standoff ends, 6.1 assumed) on arrival |
| `tilt_coupler`, `hub_drive`, `tilt_adapter`, `hub_idle` | Updated for the shoulder screw + Belleville stack; check the screw head height (3.0 assumed) |
| `body_front`, `body_back`, `body_floor`, `body_lid`, `screen_clamp` | New abdomen. Wait for the measurements below before printing `body_front` and `screen_clamp` |
| `chassis_plate`, `bumper`, `skirt_rear`, `waist_deck`, wheel hubs, tyres, casters, `dock_*` | **Obsolete** (old printed base). Redrawn round the iQ360 after 5 Nov |

Checks run on 29 Oct (head, neck and body): no overlaps, the head stays ≥ 34 mm from the body over
the full tilt and pan range (rule: > 25), everything fits the bed, and 20 supporters' names of 16
wide letters fit under the new lid (3.2 mm letters).

**Running the CAD on a laptop:** don't run `build.py` with its full checks; it needs 6–7 GB and the
desktop's OOM guard kills the terminal instead. Use `cad/tools/export_some.py <parts>` and
`cad/tools/body_checks.py` / `head_checks.py`, wrapped in `cad/tools/guard.sh 1800 …` (each peaks
at 0.5–0.8 GB).

## Measurements needed (each is one number in `cad/params.py`)

- **7" screen:** outline, thickness, visible area, where the ribbon leaves (drawn as 165 × 100 × 8, window 156 × 87)
- **Z200 drivers:** diameter, depth, impedance (Ω), and what the power adapter says (amp swap or keep)
- **Freenove fans:** 30 or 40 mm; **Freenove M.2 board:** outline
- **DualEye:** glass front to standoff ends; **shoulder screw:** head height
- **iQ360 (5 Nov):** diameter and weight, wheel positions, motor wire count (brushed or brushless), lidar model, connector and height, cliff sensor positions, battery voltage
- **Heat-set inserts:** outside diameter (sets `M3_INSERT_D`)

## Still to buy

- Wheel motor drivers (after counting the iQ360's motor wires: DRV8874 for brushed, a BLDC driver otherwise)
- Charger or dock (a 4S pack needs 16.8 V; maybe reuse the vacuum's dock)
- Four more VL53L1X (one per post)
- Four 10 mm metal tubes for the posts (length set by the band)
- A PAM8403 board if the Z200 amp can't run on plain DC

## Next CAD jobs

1. Base, waist band, posts and deck ring round the measured iQ360 parts
2. Speaker boxes (sealed, printed) once the drivers are measured
3. Brackets for the camera, boards and converters once they're in hand
4. Re-run the tip-over check with the real masses
