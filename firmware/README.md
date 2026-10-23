# Claude body: ESP32 firmware

Two PlatformIO (Arduino) projects, both for an **ESP32-S3-DevKitC-1 N8R2** (8 MB flash, 2 MB PSRAM):

| Project | Role | Protocol |
|---|---|---|
| `base/` | "Spinal cord": wheel and neck servos (Feetech STS3215 bus), bumpers, drop and obstacle ToFs, IMU, battery, dock, chest LED ring, **all safety reflexes** | `docs/PROTOCOL.md` §1 |
| `face/` | Two round LCD eyes, camera visor, ears, head-pat touch pad | `docs/PROTOCOL.md` §2 |

Both talk newline-delimited JSON over native USB CDC at 921600, send `hello` at boot (and again whenever the
Pi reopens the port), and ignore unknown message types.

Every pin is in `<project>/include/pins.h`, which starts with a wiring comment block. Tunables (speeds,
thresholds, servo pulse widths, colours) are in `<project>/include/config.h`.

```
base/  include/{pins.h,config.h}
       lib/core/      hardware-free logic: kinematics, odometry unwrap, speed/accel governor,
                      reflex state machine, drop/floor calibration, battery/NTC/dock, IMU filter,
                      LED animations, JSON parser/formatters      <- unit-tested on the PC
       src/           main.cpp, sts_bus (Feetech), tof (5x VL53L1X), imu_bno085 / imu_mpu6050
       test/          native Unity tests
face/  include/{pins.h,config.h}
       lib/core/      moods -> poses, transitions, eye geometry, blink scheduler, ears,
                      touch gestures, visor state machine, JSON parser  <- unit-tested
       src/           main.cpp, eyes.cpp (LovyanGFX renderer), servo_pwm.h
       test/
```

## Build and test

```bash
PIO=~/.platformio/penv/bin/pio
cd base && $PIO run && $PIO test -e native     # env "base" (BNO085); also "base_mpu6050", "base_bench"
cd ../face && $PIO run && $PIO test -e native
```

The platform is pinned (pioarduino 55.03.39 = Arduino-ESP32 3.3.9 / ESP-IDF 5.5) and so is every library:
FTServo 2.0.0 (Feetech's own), Pololu VL53L1X 1.3.1, Adafruit BNO08x 1.2.7, Adafruit NeoPixel 1.15.4,
LovyanGFX 1.2.32, ArduinoJson 7.4.3.

## Flashing safely (read this first)

Several ESP32s are often plugged into the laptop, and flashing the wrong one has caused trouble before. **Never run a bare
`pio run -t upload`**: PlatformIO picks a port by itself.

1. Unplug every other ESP32 you can.
2. `ls -l /dev/serial/by-id/` and note the `usb-Espressif_USB_JTAG_serial_debug_unit_<MAC>-if00` entry
   for *this* board (the MAC is printed on the board's label or by `esptool.py read_mac` on that port).
3. Upload with the port given explicitly:
   `$PIO run -e base -t upload --upload-port /dev/serial/by-id/usb-Espressif_..._<MAC>-if00`
4. Write the by-id path for each board on a sticker on the board.

Native USB note: these boards enumerate through the S3's built-in USB-Serial/JTAG (the "USB" connector,
not the "UART" one). If an upload ever fails to start, hold BOOT, tap RESET, release BOOT.

## Wiring: base

| GPIO | Part | Notes |
|---|---|---|
| 17 | Waveshare Bus Servo Adapter (A) **RX** | ESP TX. Jumper on **A** (UART). |
| 18 | Waveshare Bus Servo Adapter (A) **TX** | ESP RX. *If the first ping finds nothing, swap 17/18:* the header's label convention is unchecked. |
| GND | adapter GND | common ground with the servo supply |
| 8 | I2C SDA | 5x VL53L1X + IMU, 2.2 k pull-ups once, 400 kHz |
| 9 | I2C SCL | |
| 10 | VL53L1X **down front-left** (+27°, r 100 mm) XSHUT | addr 0x30, `drop[0]` |
| 11 | VL53L1X **down REAR** (145°, r 95 mm) XSHUT | addr 0x31, `drop[1]` (the "c" slot) |
| 12 | VL53L1X **down front-right** (−27°, r 100 mm) XSHUT | addr 0x32, `drop[2]` |
| 13 | VL53L1X **forward-left** XSHUT | addr 0x33 |
| 14 | VL53L1X **forward-right** XSHUT | addr 0x34 |
| (I2C) | BNO085 (default) | I2C mode, addr 0x4A, INT/RST not connected |
| (I2C) | MPU-6050 (alternative build) | AD0 to GND, addr 0x68 |
| 15 | bumper left micro-switch | COM to GND, NO to GPIO (internal pull-up, pressed = LOW) |
| 16 | bumper right micro-switch | same |
| 1 | battery sense | PACK+ to 100 k to GPIO1 to 22 k to GND (+100 nF) |
| 2 | pack NTC 10 k B3950 | 3V3 to 10 k 1 % to GPIO2 to NTC to GND (+100 nF) |
| 4 | charge-contact sense | CONTACT+ (before the diode) to 100 k to GPIO4 to 22 k to GND (+100 nF) |
| 5 | motor kill-switch sense (ADC) | servo rail after the rocker to 100 k to GPIO5 to 33 k to GND (+100 nF). Read as a voltage: on above 7 V, off below 6 V |
| 21 | WS2812 ring, **16 LEDs** | 330 R in series; 1000 µF across the ring's 5 V |

Servo power: 3S pack, then the motor kill rocker, then the adapter's power input, which feeds the servos directly.
The pack has a fuse on each branch: **7.5 A** on the servo branch and **3 A** on the Pi/buck branch. There is also
a **1000 µF** bulk cap on the buck output. The motor-power sense sits on the servo branch after the rocker, so a
blown 7.5 A fuse reads exactly like the rocker being off: `motors:false`, `fault:"motors_off"`, and the bus is held
limp. No firmware change was needed for this.
The head has its own 5 V 3 A buck from the pack through a polyfuse, which feeds the ear and visor servos, the mic amp
and the LCDs (see *Wiring: face*). The Pi's buck only feeds the Pi and what hangs off it.
Buy the **12 V STS3215** (C018/C047, 1:345). Bus IDs: **1 = left wheel, 2 = right wheel (mounted mirrored),
3 = neck pan, 4 = head tilt.**

Sensor geometry the firmware assumes: down ToFs about 50 mm above the floor (floor calibration measures the
real value), and forward ToFs 45 mm behind the bumper face (`FWD_TOF_OFFSET_MM`). Obstacle thresholds are
measured from the bumper face, so "60 mm" means 105 mm at the sensor, safely above the VL53L1X's 40 mm minimum.

## Wiring: face

| GPIO | Part | Notes |
|---|---|---|
| 12 | both LCDs SCL/SCK | FSPI IO_MUX pin (needed for 80 MHz) |
| 11 | both LCDs SDA/MOSI | FSPI IO_MUX pin |
| 8 | both LCDs DC | |
| 14 | both LCDs RST | |
| 10 | **left** eye CS | robot's left (the viewer's right) |
| 9 | **right** eye CS | |
| 7 | both backlights (BLK) | through a logic-level N-MOSFET, or direct if the module has its own transistor |
| 4 | visor (shutter) MG90S signal | head 5 V rail, common GND |
| 5 | visor-UP limit switch | COM to GND, NO to GPIO (pull-up); **closed = visor fully up** |
| 15 | left ear servo signal | |
| 16 | right ear servo signal | mounted mirrored (see `EAR_R_*_US`) |
| 6 | TTP223 touch OUT | default jumpers (active HIGH, momentary), VCC 3V3 |
| 17 | head VL53L1X SDA | forward-looking, at head height; 2.2 k pull-up; only device on this bus (0x29) |
| 18 | head VL53L1X SCL | 2.2 k pull-up |
| 21 | head VL53L1X XSHUT | lets the firmware reset a hung sensor |

The head VL53L1X sends `{"t":"range","head_mm":N}` at 10 Hz. -1 means no reading (a dead or stale sensor;
the body treats it as slow) and 4000 means clear. It runs in long-distance mode with a 50 ms timing budget. A dead
sensor is re-initialised every 30 s; that blocks about 60 ms, so the eyes hitch for one frame.

**Head power.** The three MG90S servos (two ears and the visor/shutter), the mic amp and the LCDs run from their own
**head 5 V rail**. That is a separate **5 V 3 A buck, fed from the pack through a polyfuse**, not the Pi's buck, so servo
stalls and current spikes can't brown out the Pi. The face ESP32 shares GND with that rail. No pins or sensing changed
for this.

Keep the LCD SPI wires short (under 10 cm). Each frame is 2 × 115 kB, so 30 fps or more needs the 80 MHz SPI clock.
At 40 MHz it would be about 21 fps.

## Setting servo IDs (once, before assembly)

Every STS3215 ships as **ID 1**, so set the IDs one servo at a time with **only that servo on the bus**.

Easiest: put the Waveshare adapter (A) in **USB mode (jumper B)**, connect it to a PC and use Feetech's FD
software (Windows) or the Python SDK. This needs `pip install feetech-servo-sdk`; it is a sketch I have **not run**:

```python
from scservo_sdk import PortHandler, PacketHandler
port = PortHandler("/dev/serial/by-id/<the adapter>"); port.openPort(); port.setBaudRate(1_000_000)
pk = PacketHandler(0)
print(pk.ping(port, 1))                 # (model 777, result, error) for a factory STS3215
NEW = 2                                 # 1 left wheel, 2 right wheel, 3 pan, 4 tilt
pk.write1ByteTxRx(port, 1, 40, 0)       # torque off
pk.write1ByteTxRx(port, 1, 55, 0)       # unlock EEPROM
pk.write1ByteTxRx(port, 1, 5, NEW)      # ID
pk.write1ByteTxRx(port, NEW, 55, 1)     # lock (now answering on the new ID)
print(pk.read1ByteTxRx(port, NEW, 14))  # max input voltage, 0.1 V: must be >= 130 for a 3S pack
```

While each servo is on the bench, also do this:
- **Max input voltage (reg 14).** Must be at least 130 (13.0 V). The 7.4 V table default is 80. The base reports
  `servo_error` with detail `vmax=8.0V(reg14)` if it finds a low value, but it **does not** rewrite it.
- **Pan and tilt mid-point.** With the neck mechanically centred (facing forward, level), write 128 to reg 40.
  That makes the current position 2048, which the firmware treats as 0°.
- **Pan and tilt angle limits.** The base writes these itself (EEPROM regs 9 and 11, in steps). Pan gets −150..150°.
  Tilt gets **−15..30°**, which is 1° inside the −16° / +31° mechanical stops. The `head` command is clamped to
  the same range.
- **Wheel mode.** The base checks reg 33 at every servo init and writes it (EEPROM, with torque off) only if it
  differs: 1 for IDs 1 and 2, 0 for IDs 3 and 4. It then reads the value back. A servo whose mode cannot be
  confirmed never gets torque (`servo_error` with `mode_unknown` or `mode_wrong`).
- **Torque limit and overload protection.** The base writes these at every servo init, but only when a value differs.
  It then **reads every value back**. A servo that doesn't verify never gets torque
  (`servo_error` with detail `verify_<name>`). The table is in `base/lib/core/src/servo_cfg.cpp`:

  | Register (regs.csv V3.7) | Wheels (IDs 1, 2) | Pan / tilt (IDs 3, 4) |
  |---|---|---|
  | 16 max torque, EEPROM (0.1 %) and 48 torque limit, SRAM | 300 = **30 %** (ceiling) | 100 = **10 %** (ceiling: must never push hard enough to hurt a child's face) |
  | 28 protection current (6.5 mA) | 150 = 975 mA | 60 = 390 mA |
  | 36 overload torque (%) | 25 | 8 |
  | 35 protection time (10 ms) | 100 = 1.0 s | 50 = 0.5 s |
  | 38 overcurrent protection time (10 ms) | 100 = 1.0 s | 50 = 0.5 s |
  | 34 protection torque after a trip (%) | 10 | 5 |
  | 19 unloading conditions | current (bit 3) + overload (bit 5) forced on | same |
  | 9 / 11 angle limits | (none, wheel mode) | pan ±150°, tilt −15..30° |

  The table doesn't say whether the % values are of stall torque or of reg 16. The values above are protective
  under either reading. Check on the bench by stalling a wheel gently by hand: watch `diag` load and status, and
  expect a `servo_error` with `status=0x20` (overload) after about 1 s.

## First power-on: bring-up order

DESIGN.md's testing rule applies: **Nick present for every step that moves anything. The first drives happen
on the bench with the wheels off the ground.** Each step is read-only until the one before it is right.

1. **Set conservative limits before flashing the base.** In `base/include/config.h`, set
   `WHEEL_TORQUE_LIMIT 100` (10 %). The design value of 300 comes later. The head is already at its permanent
   ceiling of 100 (10 %).
2. **Face, alone on USB.** Flash it and open a serial monitor. Expect `{"t":"hello","fw":"face 0.1.0"}` and
   `visor` `moving`, then `closed`. **At boot the visor servo drives closed and the ears go to half**, so keep fingers
   clear. Send `{"t":"diag"}` and check `psram_ok:true` and the `fps` (target 30 or more). Try moods, `gaze`, `blink`
   and `bright`. Pat the pad and watch for `touch` events. Command `{"t":"visor","open":true}` and check that
   `open` appears only when the switch actually clicks, then unplug the switch and check you get `jammed`.
3. **Base on USB only, kill rocker OFF, robot on a stand with the wheels clear.** Flash the **`base_bench`** env:
   on a stand the down sensors see the bench far away, and the normal build (floor 35..90 mm) would then block
   forward motion. Its `hello` says `"fw":"base 0.1.0 bench"`. Expect `hello`, then
   `odom` and `imu` at 50 Hz and `state` at 5 Hz with `motors:false` and `fault:"motors_off"`. Check `bat_v`,
   `pack_c` (not `null`), `bump` (press each switch), `drop` and `fwd_mm` (hand in front), and that `imu` roll
   and pitch follow when you tilt the base. Send `{"t":"cal"}` and check the reply's `floor_mm` and `ok`.
   The bench build accepts floors up to 250 mm. The normal build accepts 35..90 mm, and the three down sensors
   must agree within 15 mm. If not, that sensor keeps its old value, and a sensor that really sees a drop blocks
   forward motion. That is fail-safe, not a bug.
4. **Servo power from a current-limited bench supply** (12 V, about 1 A) in place of the pack, then rocker ON.
   `{"t":"diag"}` should show 4 servos `online`, `bus_echo` true or false (auto-detected), and no `servo_error`
   events. A missing or `no_reply` servo usually means swapped TX/RX or a wrong ID.
5. **Head.** Do the pan/tilt mid-point calibration first (see "Setting servo IDs"): the EEPROM angle limits are
   in steps relative to it. Send `{"t":"torque","on":true}`, then `{"t":"head","pan":10,"tilt":0,"speed":20}`.
   Check the direction (+pan = left, +tilt = up). Flip `PAN_DIR` or `TILT_DIR` if needed. Then sweep slowly to
   −15° and +30° tilt: it must stop short of the −16° / +31° mechanical stops. Push the head gently by hand: at
   10 % torque it should give way easily.
6. **Wheels, still off the ground.** Stream `{"t":"vel","v":0.03,"w":0,"seq":N}` at 10 Hz for 2 s. Both wheels
   should turn "forward" and `odom.x` should increase. Then check these:
   - Stop streaming: the wheels must ramp to a stop within about 0.3 s and you get a `watchdog` event.
   - Spin (`w:0.5`): `odom.th` increases (counter-clockwise, left turn).
   - While turning, press a bumper: they stop at once, `bump_l` or `bump_r`. Forward is refused for 1 s after
     release, and reverse works up to 0.08 m/s.
   - Tilt the stand past 15°: the wheels brake and the head goes limp at once (`tilt`). The wheels go limp once
     they reach zero, or after 0.3 s. Recovery needs 2 s under 10° and then `torque on`.
   - Lift a front drop sensor's view: `drop_l` or `drop_r`, forward refused, reverse allowed up to 0.08 m/s.
     Lift the rear one: `drop_rear`, reverse refused, forward allowed up to 0.08 m/s.
7. Only then raise the torque limits to the design values, flash the normal **`base`** env (never drive on the
   floor with `base_bench`), move to the pack, and do floor tests together.

## Protocol decisions (where PROTOCOL.md was open)

Base:
- **`cal` (new, Pi to base).** Re-runs the down-sensor floor calibration (median of 15 readings each) and
  answers `{"t":"cal","floor_mm":[l,c,r],"ok":[..]}`. It also runs at boot. Motion is blocked while it runs.
- **`diag` (new).** Returns servo, bus, ToF and loop statistics. **`limits`** is answered with the effective caps.
- **`stop`.** Zeroes the wheels immediately and brakes (torque on, speed 0) for 200 ms, then turns *wheel*
  torque off (coast). The next non-zero `vel` re-enables it. The head is untouched.
- **Torque bookkeeping.** One function decides whether each servo should have torque (the `torque` command,
  tilt latch, `stop`, motor power, and the servo's mode check). That decision is re-applied every tick and checked
  against reg 40 by readback, so a lost write or a servo brown-out gets repaired. Torque-off is sent even to a
  servo marked offline. The wheels are only driven when **both** have torque, never one alone.
- **Motor power off.** While the kill-switch sense reads off, the base broadcasts torque-off and zero speed every
  tick. A wrong reading can therefore never leave a powered wheel running.
- **Servo start-up.** It waits until boot is complete (IMU and floor calibration done), so a robot powered on its
  side never gets torque.
- **Servo presence.** Checked by reading regs 3..5, not by PING, because an echoing adapter can fake a PING reply.
- **Wheel torque faults.** Status bits for temperature, current or overload on a wheel block motion
  (`fault:"servo_error"`) until they clear.
- **Speeding up is ramped at a_max, per wheel.** Both wheels are scaled together, so the path's curvature is kept.
  Slowing down follows the braking rules below.
- **Drop sensor layout.** The `drop` field keeps PROTOCOL.md's `[l,c,r]` order, but **c is the REAR sensor**:
  [front-left +27°, REAR 145°, front-right −27°; radii 100 / 95 / 100 mm], because the robot reverses onto its dock. `floor_mm` and `ok`
  in the `cal` reply use the same order. Events are **`drop_l`, `drop_rear`, `drop_r`**.
- **Emergency braking.** Bump, drop, tilt, obstacle under 60 mm, pack hot and `stop` all brake at
  **A_ESTOP = 1.5 m/s²**. The watchdog, the 120 mm slow zone and ordinary slowing use a_max (0.5). Speeding up is
  always a_max. The native test measures **18.4 mm** of travel from 0.25 m/s, over 8 ticks of 20 ms after the trigger.
  Sensor latency comes on top. Bump and drop then hold zero with torque. `stop` holds zero for 200 ms, then coasts.
  Only "no power" cases (motors off, servo comms lost) zero at once.
- **Tilt** is 15° (the static tip point over the wheel-to-rear-ball diagonal is about 19–21°, so 15° stays below it). The head goes limp at once. The
  wheels brake at A_ESTOP and go limp when stopped, or after 0.3 s at most. "Upright" for recovery means under 10°.
- **Direction rules.** A front drop (l or r) or a bump refuses forward and allows reverse up to 0.08 m/s. A rear
  drop refuses reverse and allows forward up to 0.08 m/s. Front and rear together allow no linear motion at all.
- **Turning during bump or drop** is allowed up to `REFLEX_W_MAX` = 0.5 rad/s in every case, so the Pi can rotate
  away. The bench build follows the same rules.
- **Bump hold-off** is 1 s from the moment the bumper is *released*.
- **Fail-safe sensors.** A dead, stale or "no target" down ToF counts as a drop. A dead forward ToF counts as a near
  obstacle (0.05 m/s cap). A dead or stale IMU counts as tilt. An open or shorted NTC counts as `pack_hot`
  (`NTC_FAULT_BLOCKS_MOTION`). Pack below 6 V counts as a BMS cut-off.
- **`fwd_mm` units.** Distance from the bumper face. -1 means no usable reading, and 4000 means nothing in range.
- **`fault` values.** Can also be `servo_error` when a wheel servo stops answering, which blocks motion. During boot
  it is `drop` while calibrating and `tilt` while the IMU warms up. At idle with no `vel` stream it is `watchdog`.
  The `watchdog` *event* fires only when a live stream stops, not at boot.
- **`charging`.** True when on the dock and the contacts sit 0.15 V or more above the pack, because current is
  flowing through the diode. This is a heuristic, since there is no charge-current sensor.
- **`low_battery`.** Fires once below 15 % (re-arms at 20 %). It does not block motion, because docking is the Pi's job.
- **Angle conventions (REP-103).** +roll = left side up, +pitch = nose down, +yaw = turning left.
- **Torque at boot.** On (`BOOT_TORQUE_ON`): head servos hold where they are and wheels hold at zero.

Face:
- **`visor` reports.** `open` only while the switch is closed. A visor lifted by hand, or one that will not come
  down, is `jammed` and is driven closed. It is never reported as `open` unless the Pi asked for it. A `visor`
  command always gets a `visor` reply, even if nothing changed.
- **Touch gestures.** `pat` is sent after the 350 ms double-tap window. `hold` fires the moment 1.5 s is reached.
  A tap followed by press-and-hold gives `pat` then `hold`.
- **`mood` and `ears`.** A `mood` resets any `ears` override.
- **`ping` and `diag`.** Added to the face as well.

## Not verified yet

Nothing has been run on hardware. These are open until the parts are on the bench:
- **STS3215 details beyond the register addresses.** All three sources agree on the addresses (Feetech's ST3215
  memory table V3.7, the FTServo 2.0.0 headers and LeRobot's control table). Still unchecked:
  - present position wrapping 0..4095 while in wheel mode (assumed, and unwrapped either way)
  - the unit of reg 48: the sheet's unit column says "1%" but the range is 0..1000; 0.1 % assumed
  - the 12 V variant's factory value in reg 14
- **TX echo.** Whether the Waveshare adapter (A) echoes TX. It is auto-detected at every servo init; see `STS_BUS_ECHO`.
- **Frame rate.** Whether the GC9A01 modules run at 80 MHz, and the real fps: `diag` reports it.
- **BNO085 over I2C** next to five VL53L1X sensors. If the bus proves flaky, use the MPU-6050 build or the
  BNO085's UART-RVC mode.
- **Visor, ear and backlight details.** The visor and ear pulse widths, plus the polarity of the visor switch and the
  backlight. They are all in `config.h` and `pins.h`.
