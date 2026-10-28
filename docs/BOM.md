# Bill of materials

Prices are AUD as seen 2026-10-23 (AliExpress search pages, Core Electronics, Pakronics). "UNCONFIRMED"
means the exact listing or size wasn't verified. Measure the part before printing its bracket.
**Status:** some parts are ordered or already on hand (marked on each line); the drive motor drivers wait until the vacuum's wheel motors are checked. Datasheet sources are in the research notes; the drawings used for the CAD
are noted in `cad/params.py`.

## Brain and senses

| # | Part | Qty | Where / what to search | Each | Line | Notes |
|---|---|---|---|---|---|---|
| 1 | Raspberry Pi 5, **8 GB** | 1 | On hand | 0 | 0 | **Have it.** Powered from the 5 V buck on GPIO: needs `PSU_MAX_CURRENT=5000` + `usb_max_current_enable=1` |
| 2 | Pi 5 Active Cooler | 1 | Core / AliExpress | 9 | 9 | **On hand.** |
| 3 | microSD 64 GB (A2) | 1 | anywhere | 15 | 15 | Ubuntu 24.04 + ROS 2 Jazzy **Not needed:** the Pi boots from its NVMe SSD HAT. |
| 4 | Seeed reSpeaker XVF3800 4-mic array **with XIAO ESP32-S3** | 1 | Seeed | 117 | 117 | **Ordered 28 Oct, due 4–16 Nov.** Echo cancelling + direction of arrival + on-chip wake word. **All speech plays out through it**. Changed 2026-10-25 from the plain USB board (101991441, A$113): lower voice latency in Nick's real use |
| 5 | USB UVC camera, **IMX291 2MP 1080p, 130° M12 lens**, 4-pin 2.0 mm header (5 V, D−, D+, GND) | 1 | AliExpress | 57 | 57 | **Ordered 27 Oct.** Board looks 38 × 38 mm (not 32): widen the eye spacing to fit. Make a short lead to the neck hub. Bracket printed after it arrives |
| 6 | Mini USB 2.0 hub board (FE1.1s, 4 port) | 1 | AliExpress | 5 | 5 | In the head: camera + mic array + face ESP32 on one neck cable. **Cut its upstream VBUS** if it's self-powered, or it back-feeds 5 V into the Pi **On hand.** |
| 7 | **Waveshare ESP32-S3-DualEye LCD 1.28 (No Touch)**: ESP32-S3R8 (16 MB flash, 8 MB PSRAM) + 2 × 240×240 round IPS, splittable with an 18-pin FPC | 1 | AliExpress | 28 | 28 | **Ordered 27 Oct.** Replaces the 2 separate LCDs AND the head ESP32. Header exposes I²C + UART + GPIO0 only, so ears/shutter go on the PCA9685 (7a). Measure before redoing the eye mounts |
| 7a | PCA9685 16-channel PWM/servo board (I²C) | 3 | AliExpress | 7 | 21 | **Ordered 27 Oct, 3-pack.** 1 in the head (2 ears + shutter), 2 spares |
| 7b | Google Coral USB Accelerator (Edge TPU) | 1 | On hand | 0 | 0 | **Have it.** On-robot person/face/floor-object detection, about 2 W; frames stay local. Own 5 V 3 A buck (not the Pi's USB budget); needs airflow. libedgetpu/pycoral need community builds on Ubuntu 24.04 / Py3.12, or run it in a container like Frigate did |
| 8 | ESP32-S3-DevKitC-1 N16R8 (two USB-C; RGB LED on GPIO48) | 3 | AliExpress | 12 | 36 | Base (reflexes), head (face), 1 spare. **Ordered 27 Oct.** Octal PSRAM: GPIO35–37 are NOT free. Base talks to the Pi over native USB only, no Wi-Fi in the safety loop |
| 9 | LDROBOT STL-19P lidar ("D500 kit") | 1 | AliExpress 1005013215151320 | 97 | 97 | The LD19 is discontinued; same footprint |
| 10 | VL53L1X time-of-flight breakout | 6 | AliExpress (generic) or Pololu #3415 | 7 | 42 | **3 ordered 28 Oct** (2 forward + 1 face); the 3 drop sensors now come from the vacuum's cliff sensors. Was: 3 down (drops), 2 forward (toys), 1 in the face (table edges). **≥ 40 mm minimum range**, already designed in |
| 11 | BNO085 IMU breakout | 1 | AliExpress | 25 | 25 | Tilt/fall detection; MPU-6050 (A$3) works as a fallback **Ordered 28 Oct: MPU-6050 (GY-521)** to start; BNO085 later if tilt detection needs it. |
| 12 | TTP223 capacitive touch pad | 1 | AliExpress | 1 | 1 | Head pats **Ordered 28 Oct** (pack of 20). |
| 13 | WS2812 16-LED ring (~68 mm OD) | 1 | AliExpress | 4 | 4 | Chest light. UNCONFIRMED OD **Also ordered 28 Oct: 1 m WS2812B 5 V, 60/m, white PCB** for a status band round the base (cap brightness ~20 %, own 5 V rail, level shifter on data). Chest ring still to buy. Chest light can be ~11 LEDs off the strip wrapped round a short printed tube inside the diffuser (a halo) if no ring is bought. **Ring ordered too.** |
| 13a | 74AHCT125 level shifter (3.3 V → 5 V data for the LED strip) + 330 Ω resistor | 1 | AliExpress | 2 | 2 | **Ordered 28 Oct.** |
| 14 | 40 mm 4 Ω 3 W speaker | 1 | AliExpress | 3 | 3 | Chest, driven by the XVF3800's amp **On hand.** |
| 14a | 7" DSI IPS touch display, 800×480, for the abdomen (tilted up ~15–20°) | 1 | On hand | 0 | 0 | **Have it.** Changed 28 Oct from the 3.5" (now the fallback). Ribbon to the Pi 5's DSI port; the Pi already sits in the body. Measure outline, thickness and ribbon length before the body CAD: at ~165 mm wide it needs a wider/taller abdomen and a fresh tip-over check. Shows notes, camera view, timers, pictures; touch for kids. Flush behind a printed bezel; dims at night **500 mm Pi 5 22-pin to 15-pin DSI cable ordered 28 Oct.** |

## Muscles

| # | Part | Qty | Where | Each | Line | Notes |
|---|---|---|---|---|---|---|
| 15 | Feetech STS3215 **12 V** (C018 or C047, 1:345, 30 kg·cm) | 4 | AliExpress / Core (A$33.55) | 37 | 148 | 2 wheels, neck pan, head tilt. **Not** the 7.4 V version **2 ordered 28 Oct (12 V / 30 kg)** for neck pan and head tilt; the wheels now come from the vacuum. |
| 15a | Wheel motor drivers: **2 × TI DRV8874** carrier (4.5–37 V, 2.1 A continuous, current-sense IPROPI output to the base ESP32 for stall detection) | 2 | Pololu #4035 via Core, or clones | 15 | 30 | **Not ordered yet: first count the vacuum wheel-module wires** (2 thick + 4 thin = brushed with encoder, so DRV8874; 3 thick + hall wires = brushless, so a BLDC driver). If stall current is well over 2 A, use a Cytron MDD10A. Not the DRV8833 (10.8 V max) |
| 16 | Waveshare Bus Servo Adapter (A) | 1 | Core (A$7.75) | 8 | 8 | UART jumper = A **Ordered 28 Oct: Feetech URT-1** bus servo board instead (one board runs both servos, daisy-chained). |
| 17 | MG90S metal-gear micro servo | 3 | AliExpress | 4 | 12 | 2 ears + visor shutter. **Ordered 28 Oct** (4-pack, 1 spare) |
| 18 | Micro switch, roller lever | 2 | AliExpress | 1 | 2 | Bumper |

## Power (Nick's trade — he'll know better parts)

| # | Part | Qty | Where | Each | Line | Notes |
|---|---|---|---|---|---|---|
| 19 | 18650 cells (Molicel P28A / Samsung 35E class) | 6 | local | 8 | 48 | 3S2P, about 65 Wh |
| 20 | 3S 20 A BMS with balance | 1 | AliExpress | 5 | 5 | |
| 21 | 10 k B3950 NTC | 1 | AliExpress | 1 | 1 | On the pack, read by the base ESP32 |
| 22 | Blade fuses + inline holders: 7.5 A (servo branch), 3 A (Pi buck branch) | 2 | Jaycar | 4 | 8 | A stalled wheel must not take the brain down **On hand.** |
| 22a | 1000 µF 16 V low-ESR electrolytic | 1 | Jaycar | 2 | 2 | On the buck output: the Pi on GPIO has no input protection **On hand.** |
| 23 | Rocker switch, 19 × 13 mm cut-out | 1 | Jaycar | 2 | 2 | Motor kill (cuts servo power only) **On hand.** |
| 24 | XY-3606 synchronous buck, 9–36 V in, 5 V 6 A out (set 5.15 V) | 1 | AliExpress | 7 | 7 | For the Pi, which peaks about 3 A once the head and Coral have their own rails. **Must pass a DL24 4 A / 20 min test at ≥ 5.0 V**, then watch `vcgencmd get_throttled` in real use. If it fails, fall back to the Pololu D36V50F5 (~A$60 delivered). Not an XL4015/LM2596: they sag **3 ordered 28 Oct** (Pi, head rail, Coral + LED-strip rail). |
| 24a | 12 V buck for the servo bus, ≥ 3 A (4S in, 12.0 V out) | 1 | AliExpress | 8 | 8 | **New 28 Oct, with the 4S pack:** a full 4S pack is 16.8 V, above the 12 V STS3215's limit. Only the neck pan + head tilt are bus servos now (the wheels come from the vacuum), so 3 A is plenty **Must be BUCK-BOOST** (e.g. 8–40 V in → 12 V, 5 A): a 4S pack runs 16.8 V full down to ~12.8 V empty, so a plain buck rated 15 V minimum drops out for most of the discharge. |
| 25 | 12.6 V 2 A Li-ion charger, **RCM-marked** | 1 | local (Jaycar/Altronics) | 25 | 25 | Mains side must be Australian-approved |
| 26 | Spring contacts (pogo, ≥ 2 A) | 4 | AliExpress | 2 | 8 | 2 per pole on the robot; brass pads on the dock |
| 27 | 5 A Schottky (SS54) + polyfuse | 1 | AliExpress | 2 | 2 | Charge contacts aren't live from the pack. The pack tops out ~0.4 V low through the diode (`bat_pct` is scaled) |
| 27a | Dock: micro switch + small relay or MOSFET module | 1 | Jaycar | 6 | 6 | Dock pads only go live when a robot is pressing the switch |

## Hardware

| # | Part | Qty | Each | Line | Notes |
|---|---|---|---|---|---|
| 28 | 608ZZ bearing | 2 | 2 | 4 | Outboard wheel supports |
| 28a | 8 mm steel dowel × 30 (or cut M8 bolt shank) | 2 | 2 | 4 | Wheel axle pins, pressed into the hub |
| 29 | 6806-2RS bearing (30 × 42 × 7) | 1 | 6 | 6 | Hollow neck pan bearing **Ordered 28 Oct.** |
| 30 | 1in (25.4 mm) chrome steel ball | 2 | 2 | 4 | Printed ball casters |
| 31 | M3 heat-set inserts (Ruthex-style, hole Ø4.0) | 100 | — | 10 | **Ordered 28 Oct: brass insert kit (M2/M3, 300 pcs).** Measure the M3 OD/length and set `M3_INSERT_D`/`M3_INSERT_DEPTH` in params.py to match. |
| 32 | M3 / M2.5 / M2 screw assortments | 3 | 10 | 30 | Incl. a **D4 × M3 shoulder screw, ~4 mm shoulder** for the tilt clutch (buy 4 and 6 mm; the coupler floor gets set to suit, and its hole opens to 4.2 for the shoulder) **Ordered 28 Oct: hex socket cap kit, M2–M6, 2220 pcs**, with nuts and washers. Shoulder screws (D4 × M3, 4 + 6 mm) bought separately. M2.5 brass standoffs: **on hand.** |
| 33 | Compression springs 5 × 15 mm | 2 | — | 5 | Bumper return (13.5 mm installed, 10 at full travel) |
| 33a | M3 Belleville washers (stack of 3 each) | 6 | — | 4 | The two neck slip clutches |
| 33b | Ø4 × 3.5 mm nylon/brass sleeves (or M3 shoulder screws) | 4 | — | 3 | Bumper slides on these; 0.5 longer than the lug so it isn't clamped |
| 33c | Steel ballast: ~100 g block (30 × 36 × 12) + ~150 g washers | 2 | — | 6 | Low under the battery shelf + under the deck, 2 × M4 each |
| 33d | 5 V 3 A buck + 1 A polyfuse | 1 | — | 8 | **Covered by the 3 × XY-3606 (line 24)**: one is the head rail; add the 1 A polyfuse. Separate 5 V for the head (ear/shutter servos, mic amp, LCDs) so a stalled ear can't brown out the Pi Polyfuses **on hand.** |
| 34 | Thin flexible USB-C-to-C cable 0.5 m, silicone wire, JST-PH/XH kits | — | — | 30 | Neck cable must be *flexible*, with **USB-C at both ends** (a USB-A plug won't pass the 10 mm hub bore). Anchor the bundle at both ends so it twists, not winds **Ordered 28 Oct: 3 × 0.5 m flat silicone USB-C to C, and a JST-PH 2.0 kit.** |
| 35 | Hook-and-loop battery strap | 1 | 3 | 3 | |

## Filament (≈ 2.1 kg incl. dock)

| Material | Approx | Line |
|---|---|---|
| PETG (structure: chassis, deck, floor, lid, frame, hubs, dock) | 1.2 kg | 40 |
| PLA cream (body halves, head rear) | 0.35 kg | 15 |
| PETG charcoal (face, ball) | 0.2 kg | 10 |
| TPU 95A (tyres; ears in orange if you have it) | 0.1 kg | 25 |
| PLA orange (shutter, gears optional) | small | — |

## Total

**≈ A$1,045** all-in, before filament you already have. The biggest lines are the Pi, the mic array,
the 4 bus servos and the lidar, about 60 % of the cost between them. A cheaper path (generic LCDs,
generic buck, MPU-6050, Pi 5 from AliExpress) gets to about A$830. I'd keep the Pololu buck, the
RCM-marked charger and the branch fuses.

**Check on arrival, before printing the brackets:** STS3215 horn screw thread and stall current;
whether the XVF3800 board has its own amp (the whole echo-cancelling audio path depends on it); the
camera board size; MG90S hole spacing; VL53L1X board size.
