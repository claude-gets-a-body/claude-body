# Wire protocols

Three links. All are **newline-delimited JSON, one object per line, UTF-8**. Every message has a `"t"`
(type) field. Unknown types are ignored, never fatal. Units are SI and degrees unless stated.

---

## 1. Pi ⇄ base ESP32 ("spine") — USB CDC serial, 921600 baud

The base ESP32 owns the Feetech bus (IDs: 1 = left wheel, 2 = right wheel, 3 = neck pan, 4 = head tilt),
bumper switches, drop/obstacle ToF sensors, IMU, battery, charge contacts, and the chest LED ring.

### Pi → base

| `t` | fields | meaning |
|---|---|---|
| `vel` | `v` m/s, `w` rad/s, `seq` int | Drive command. **Must repeat at ≥ 5 Hz.** If no `vel` arrives for 300 ms → stop. |
| `head` | `pan` deg (−150..150, 0 = forward, + = left), `tilt` deg (**−15..30**, + = up; hard mechanical stops at −16 / +31), `speed` deg/s (≤ 120) | Move neck. Clamped to limits. |
| `light` | `mode`: `off`/`idle`/`listen`/`think`/`speak`/`alert`/`sleep`/`charge`, optional `rgb` [r,g,b] 0–255 | Chest ring animation. |
| `stop` | — | Immediate stop, wheels hold torque-off-coast. |
| `torque` | `on` bool | Enable/disable torque on all servos (off = limp). |
| `limits` | `v_max`, `a_max`, `w_max` | Lower the caps (can never be raised above the compiled-in caps). |
| `ping` | `id` | Reply with `pong`. |
| `cal` | — | Re-run floor calibration for the drop sensors (also runs at boot; motion blocked while it runs). Replies with per-sensor floor distances. Accepts 35–90 mm only, and the three must agree within 15 mm (the `base_bench` build accepts up to 250 mm — never on the floor). |
| `diag` | — | Reply with firmware diagnostics (servo modes, bus echo, sensor health). |

### base → Pi

| `t` | rate | fields |
|---|---|---|
| `odom` | 50 Hz | `x`,`y` m, `th` rad (integrated from wheel servo positions), `v` m/s, `w` rad/s, `ts` ms since boot |
| `imu` | 50 Hz | `roll`,`pitch`,`yaw` deg, `gz` deg/s |
| `state` | 5 Hz | `bat_v`, `bat_pct`, `charging` bool, `on_dock` bool, `pack_c` °C, `bump` [l,r] bool, `drop` [front-left, **rear**, front-right] bool, `fwd_mm` [l,r] int, `pan`,`tilt` deg (measured), `motors` bool (kill switch state), `fault` string or null |
| `event` | on change | `e`: `bump_l`, `bump_r`, `drop_l`, `drop_rear`, `drop_r`, `obstacle`, `tilt`, `watchdog`, `dock_on`, `dock_off`, `low_battery`, `pack_hot`, `servo_error`; optional `detail` |
| `pong` | reply | `id` |
| `hello` | on boot | `fw`, `caps` {`v_max`,`a_max`,`w_max`} |

### Reflexes (in the base firmware, never in the Pi)

- **Compiled caps:** `v_max` 0.25 m/s, `w_max` 1.5 rad/s, `a_max` 0.5 m/s². Ramps are applied in firmware.
- **Bump:** stop at once; refuse forward motion while the bumper is pressed and for 1 s after; reverse
  is allowed at up to 0.08 m/s.
- **Drop (any down-ToF > 60 mm beyond calibrated floor):** stop. A front drop (l or r) blocks forward motion
  (reverse up to 0.08 m/s allowed). The rear drop blocks reverse (forward up to 0.08 m/s allowed). Both
  together allow rotation only (≤ 0.5 rad/s). A dead or stale drop sensor counts as a drop.
- **Obstacle (forward ToF < 120 mm):** forward speed capped at 0.05 m/s; < 60 mm → no forward motion.
- **Tilt** (|roll| or |pitch| > 15°): torque off on all servos until the robot is upright for 2 s
  and a `torque on` arrives.
- **Watchdog:** 300 ms without `vel` → ramp to zero at `a_max`.
- **Emergency stops** (bump, drop, tilt, obstacle < 60 mm) brake at `A_ESTOP` = 1.5 m/s², not `a_max`: from 0.25 m/s that's 21 mm + about 25 mm latency, inside the 89 mm the front drop sensors sit ahead of the wheels.
- **Pack over 50 °C or BMS cutoff detected:** stop, `pack_hot` event, light `alert`.
- `fault` is the most recent active reason motion is blocked (`bump`, `drop`, `obstacle`, `tilt`, `watchdog`, `pack_hot`, `motors_off`, `servo_error`) or null.
- `fwd_mm` is measured from the bumper face (`FWD_TOF_OFFSET_MM` = 45 behind it); -1 = no usable reading, 4000 = nothing in range.

---

## 2. Pi ⇄ head ESP32 ("face") — USB CDC serial, 921600 baud

Owns the two round LCD eyes, the visor servo + visor-open switch, two ear servos, and the touch pad.

### Pi → face

| `t` | fields | meaning |
|---|---|---|
| `mood` | `m`: `neutral`/`happy`/`curious`/`thinking`/`sad`/`surprised`/`sleepy`/`asleep`/`confused`/`listening`, optional `ms` transition time | Eye shape + ear pose preset |
| `gaze` | `x`,`y` −1..1 | Where pupils point (−1 = robot's left/down) |
| `blink` | — | Blink now (the face also blinks on its own every 2–6 s) |
| `ears` | `l`,`r` 0..1 (0 = down, 1 = up), or `wiggle`: true | Override ear pose |
| `visor` | `open` bool | Raise/lower the camera visor |
| `bright` | `b` 0..1 | Display backlight |

### face → Pi

| `t` | when | fields |
|---|---|---|
| `visor` | on change | `state`: `open`/`closed`/`moving`/`jammed` — `open` **only** when the visor-up switch is closed |
| `touch` | on gesture | `g`: `pat` (short), `hold` (> 1.5 s), `double` |
| `range` | 10 Hz | `head_mm` int: forward VL53L1X in the face, at head height (−1 = no reading, 4000 = clear). Catches table edges and benchtops the lidar plane (138 mm) can't see |
| `hello` | boot | `fw` |

**Rule:** the body agent must not read the camera unless the last `visor` state is `open`. On boot the
face closes the visor.

---

## 3. Body agent (Pi) ⇄ mind (K8) — WebSocket, `ws://k8:8765/body`

JSON messages, one per WebSocket frame. Auth: `Authorization: Bearer <BODY_TOKEN>` header on connect.

### body → mind

| `t` | fields | meaning |
|---|---|---|
| `hello` | `body_id`, `fw` {base, face}, `caps` [list of tool names it can execute] | On connect |
| `heard` | `text`, `speaker` (name or null), `doa` deg (relative to body forward), `conf` 0..1, `id`, optional `handled` | Final speech-to-text of one utterance after the wake word / during a follow-up window. `handled` names a stop word ("stop", "go away", "stop looking") the body already acted on before the mind heard it |
| `saw` | `people`: [{`name` or null, `bearing` deg, `dist_m`}], `ts` | Change in who is visible (debounced, ≤ 1/s) |
| `touch` | `g` | Head pat etc. |
| `state` | `battery_pct`, `charging`, `docked`, `place` (named place or null), `fault`, `quiet_hours` bool | Every 30 s and on change |
| `event` | `e`, `detail` | Base reflex events worth knowing about (bump, drop, low battery, stuck) |
| `tool_result` | `call_id`, `ok` bool, `result` (JSON) or `error` string, optional `image_b64` (JPEG) | Reply to a `tool_call` |

### mind → body

| `t` | fields | meaning |
|---|---|---|
| `tool_call` | `call_id`, `name`, `args` | Execute a body tool: `say`, `express`, `look`, `turn_to`, `go_to`, `approach`, `dock`, `sleep`, `wake`, `stop` |
| `listen` | `seconds` | Open a follow-up listening window without the wake word (after asking a question) |
| `speak_state` | `on` bool | Mind is generating — body shows `thinking` |

`say` args: `text`, optional `voice_style`. The body runs TTS (via K8 Piper HTTP) and plays it,
returning `tool_result` when playback finishes (or `ok:false` if interrupted by a new wake word).
