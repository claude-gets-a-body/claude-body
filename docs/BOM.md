# Bill of materials

Prices are AUD as seen 2026-10-23 (AliExpress search pages, Core Electronics, Pakronics). "UNCONFIRMED"
means the exact listing or size wasn't verified. Measure the part before printing its bracket.
**Nothing has been ordered.** Datasheet sources are in the research notes; the drawings used for the CAD
are noted in `cad/params.py`.

## Brain and senses

| # | Part | Qty | Where / what to search | Each | Line | Notes |
|---|---|---|---|---|---|---|
| 1 | Raspberry Pi 5, 4 GB | 1 | Core Electronics | 178 | 178 | Powered from the 5 V buck on GPIO: needs `PSU_MAX_CURRENT=5000` + `usb_max_current_enable=1` |
| 2 | Pi 5 Active Cooler | 1 | Core / AliExpress | 9 | 9 | |
| 3 | microSD 64 GB (A2) | 1 | anywhere | 15 | 15 | Ubuntu 24.04 + ROS 2 Jazzy |
| 4 | Seeed reSpeaker XVF3800 4-mic array **with XIAO ESP32-S3** (the lounge unit's kit; check the SKU and price before ordering) | 1 | Pakronics / Seeed | TBC | TBC | Echo cancelling + direction of arrival + on-chip wake word. **All speech plays out through it**. Changed 2026-10-25 from the plain USB board (101991441, A$113): lower voice latency in Nick's real use |
| 5 | USB UVC camera module, ~120° wide, 1080p, ≤32 × 32 mm board | 1 | AliExpress "USB camera module 120 degree" | 20 | 20 | UNCONFIRMED board size; the bracket prints after it arrives |
| 6 | Mini USB 2.0 hub board (FE1.1s, 4 port) | 1 | AliExpress | 5 | 5 | In the head: camera + mic array + face ESP32 on one neck cable. **Cut its upstream VBUS** if it's self-powered, or it back-feeds 5 V into the Pi |
| 7 | Waveshare 1.28in round LCD module (SKU 19192, GC9A01) | 2 | Waveshare store | 23 | 46 | The eyes. Generic AliExpress ones are A$6 but undocumented holes |
| 8 | ESP32-S3-DevKitC-1 N8R2 | 2 | AliExpress (Espressif store) | 12 | 24 | One in the base (reflexes), one in the head (face) |
| 9 | LDROBOT STL-19P lidar ("D500 kit") | 1 | AliExpress 1005013215151320 | 97 | 97 | The LD19 is discontinued; same footprint |
| 10 | VL53L1X time-of-flight breakout | 6 | AliExpress (generic) or Pololu #3415 | 7 | 42 | 3 down (drops), 2 forward (toys), 1 in the face (table edges). **≥ 40 mm minimum range**, already designed in |
| 11 | BNO085 IMU breakout | 1 | AliExpress | 25 | 25 | Tilt/fall detection; MPU-6050 (A$3) works as a fallback |
| 12 | TTP223 capacitive touch pad | 1 | AliExpress | 1 | 1 | Head pats |
| 13 | WS2812 16-LED ring (~68 mm OD) | 1 | AliExpress | 4 | 4 | Chest light. UNCONFIRMED OD |
| 14 | 40 mm 4 Ω 3 W speaker | 1 | AliExpress | 3 | 3 | Chest, driven by the XVF3800's amp |
| 14a | 3.5" display for the abdomen (DSI or HDMI, 480×320 or better, for the Pi 5) | 1 | AliExpress | TBC | ~30 | Notes, camera view, timers. Added 2026-10-25 at Nick's request |

## Muscles

| # | Part | Qty | Where | Each | Line | Notes |
|---|---|---|---|---|---|---|
| 15 | Feetech STS3215 **12 V** (C018 or C047, 1:345, 30 kg·cm) | 4 | AliExpress / Core (A$33.55) | 37 | 148 | 2 wheels, neck pan, head tilt. **Not** the 7.4 V version |
| 16 | Waveshare Bus Servo Adapter (A) | 1 | Core (A$7.75) | 8 | 8 | UART jumper = A |
| 17 | MG90S metal-gear micro servo | 3 | AliExpress | 4 | 12 | 2 ears + visor shutter |
| 18 | Micro switch, roller lever | 2 | AliExpress | 1 | 2 | Bumper |

## Power (Nick's trade — he'll know better parts)

| # | Part | Qty | Where | Each | Line | Notes |
|---|---|---|---|---|---|---|
| 19 | 18650 cells (Molicel P28A / Samsung 35E class) | 6 | local | 8 | 48 | 3S2P, about 65 Wh |
| 20 | 3S 20 A BMS with balance | 1 | AliExpress | 5 | 5 | |
| 21 | 10 k B3950 NTC | 1 | AliExpress | 1 | 1 | On the pack, read by the base ESP32 |
| 22 | Blade fuses + inline holders: 7.5 A (servo branch), 3 A (Pi buck branch) | 2 | Jaycar | 4 | 8 | A stalled wheel must not take the brain down |
| 22a | 1000 µF 16 V low-ESR electrolytic | 1 | Jaycar | 2 | 2 | On the buck output: the Pi on GPIO has no input protection |
| 23 | Rocker switch, 19 × 13 mm cut-out | 1 | Jaycar | 2 | 2 | Motor kill (cuts servo power only) |
| 24 | Pololu D36V50F5 5 V 5.5 A buck | 1 | Core / Pololu | 62 | 62 | For the Pi. Cheap XL4015s rarely do a real 5 A |
| 25 | 12.6 V 2 A Li-ion charger, **RCM-marked** | 1 | local (Jaycar/Altronics) | 25 | 25 | Mains side must be Australian-approved |
| 26 | Spring contacts (pogo, ≥ 2 A) | 4 | AliExpress | 2 | 8 | 2 per pole on the robot; brass pads on the dock |
| 27 | 5 A Schottky (SS54) + polyfuse | 1 | AliExpress | 2 | 2 | Charge contacts aren't live from the pack. The pack tops out ~0.4 V low through the diode (`bat_pct` is scaled) |
| 27a | Dock: micro switch + small relay or MOSFET module | 1 | Jaycar | 6 | 6 | Dock pads only go live when a robot is pressing the switch |

## Hardware

| # | Part | Qty | Each | Line | Notes |
|---|---|---|---|---|---|
| 28 | 608ZZ bearing | 2 | 2 | 4 | Outboard wheel supports |
| 28a | 8 mm steel dowel × 30 (or cut M8 bolt shank) | 2 | 2 | 4 | Wheel axle pins, pressed into the hub |
| 29 | 6806-2RS bearing (30 × 42 × 7) | 1 | 6 | 6 | Hollow neck pan bearing |
| 30 | 1in (25.4 mm) chrome steel ball | 2 | 2 | 4 | Printed ball casters |
| 31 | M3 heat-set inserts (Ruthex-style, hole Ø4.0) | 100 | — | 10 | |
| 32 | M3 / M2.5 / M2 screw assortments | 3 | 10 | 30 | Incl. an M3 × 10 shoulder screw for the tilt clutch |
| 33 | Compression springs 5 × 15 mm | 2 | — | 5 | Bumper return (13.5 mm installed, 10 at full travel) |
| 33a | M3 Belleville washers (stack of 3 each) | 6 | — | 4 | The two neck slip clutches |
| 33b | Ø4 × 3.5 mm nylon/brass sleeves (or M3 shoulder screws) | 4 | — | 3 | Bumper slides on these; 0.5 longer than the lug so it isn't clamped |
| 33c | Steel ballast: ~100 g block (30 × 36 × 12) + ~150 g washers | 2 | — | 6 | Low under the battery shelf + under the deck, 2 × M4 each |
| 33d | 5 V 3 A buck + 1 A polyfuse | 1 | — | 8 | Separate 5 V for the head (ear/shutter servos, mic amp, LCDs) so a stalled ear can't brown out the Pi |
| 34 | Thin flexible USB-C-to-C cable 0.5 m, silicone wire, JST-PH/XH kits | — | — | 30 | Neck cable must be *flexible*, with **USB-C at both ends** (a USB-A plug won't pass the 10 mm hub bore). Anchor the bundle at both ends so it twists, not winds |
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
