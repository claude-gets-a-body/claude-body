// =============================================================================
//  Claude body -- BASE firmware ("spinal cord"). PROTOCOL.md section 1.
//
//  One cooperative loop, no RTOS tasks, no long delays:
//    every pass   : USB serial in, bumpers (1 kHz), one ToF poll, IMU poll
//    50 Hz        : reflexes -> drive governor -> wheel servos -> odom + imu out
//    5 Hz         : head feedback, battery/NTC/dock ADCs, `state` out
//    50 Hz        : chest ring
//  Safety logic lives in lib/core (reflex.cpp, motion.cpp) and is unit-tested
//  on the host; this file is wiring.
// =============================================================================
#include <Adafruit_NeoPixel.h>
#include <Arduino.h>
#include <Wire.h>

#include "config.h"
#include "debounce.h"
#include "events.h"
#include "floor.h"
#include "head.h"
#include "imu.h"
#include "kinematics.h"
#include "led_anim.h"
#include "line_buffer.h"
#include "motion.h"
#include "pins.h"
#include "power.h"
#include "protocol.h"
#include "reflex.h"
#include "servo_cfg.h"
#include "sts_bus.h"
#include "tof.h"

// ---- objects -------------------------------------------------------------------
static StsBus bus;
static TofArray tofs;
static Imu imuDev;
static Adafruit_NeoPixel ring(LED_COUNT, PIN_LED_RING, NEO_GRB + NEO_KHZ800);

static motion::Drive drive({{CAP_V_MAX, CAP_W_MAX, CAP_A_MAX}, TRACK_WIDTH_M, CAP_WHEEL_V_MAX,
                            WATCHDOG_MS, STOP_BRAKE_MS, A_ESTOP});
static reflex::Reflexes reflexes(reflex::defaultConfig());
static power::Monitor powerMon(power::defaultConfig());
static tof::FloorCal floorCal(CAL_SAMPLES, CAL_TIMEOUT_MS, CAL_MIN_MM, CAL_MAX_MM,
                              FLOOR_DEFAULT_MM, CAL_AGREE_MM);
static tof::DropDetector dropDet[3] = {{DROP_MARGIN_MM, DROP_CLEAR_MS},
                                       {DROP_MARGIN_MM, DROP_CLEAR_MS},
                                       {DROP_MARGIN_MM, DROP_CLEAR_MS}};
static Debouncer bumpL(BUMP_PRESS_MS, BUMP_RELEASE_MS), bumpR(BUMP_PRESS_MS, BUMP_RELEASE_MS);
static Debouncer motorSense(MOTOR_SENSE_DEBOUNCE_MS, MOTOR_SENSE_DEBOUNCE_MS);
static bool motorRailHigh = false;  // hysteresis state of the analogue rail reading
static kin::Odometry odom(TRACK_WIDTH_M);
static kin::WheelUnwrapper unwrapL, unwrapR;
static EventQueue events;
static LineBuffer<PI_LINE_MAX> rxLine;

// ---- state -----------------------------------------------------------------------
static bool bootDone = false;
static uint32_t bootStartMs = 0;
static bool calReplyPending = false;

static bool torqueWanted = BOOT_TORQUE_ON;  // global `torque` state

static led::Mode lightMode = led::IDLE;
static led::Rgb lightRgb = led::defaultColour(led::IDLE);

struct ServoSlot {
  uint8_t id;
  bool wheel;
  servo::Kind kind;
  bool online = false;
  bool errReported = false;
  int fails = 0;
  uint8_t lastStatus = 0;
  ServoFeedback fb;
  uint32_t fbMs = 0;
  bool torque = false;   // what we believe reg 40 holds (verified by readback)
  bool faulted = false;  // operating mode wrong/unknown: never given torque
};
static ServoSlot servos[4] = {{SERVO_ID_LEFT, true, servo::WHEEL},
                              {SERVO_ID_RIGHT, true, servo::WHEEL},
                              {SERVO_ID_PAN, false, servo::PAN},
                              {SERVO_ID_TILT, false, servo::TILT}};
enum { S_LEFT = 0, S_RIGHT, S_PAN, S_TILT };

static bool motorsOn = false;
static bool tiltBraking = false;  // tilt latched: wheels brake at A_ESTOP before going limp
static uint32_t tiltT0 = 0;
static int initStep = -1;          // -1 idle, 0..3 initialising servo n, 4 done
static uint32_t initAtMs = 0;      // start init after this time
static uint32_t lastRecoverMs = 0;
static int64_t totalL = 0, totalR = 0, odomL = 0, odomR = 0;

// head target (applied when servos are up and torque is on)
static bool headPending = false;
static float headPan = 0, headTilt = 0, headSpeed = HEAD_SPEED_DEFAULT_DPS;

// stats
static uint32_t loopCount = 0, loopHz = 0, statWindowMs = 0, txDropped = 0;

// ---- output ------------------------------------------------------------------------
static void sendLine(const char* s, size_t n) {
  if (n == 0) return;
  // Never block on USB: if the host isn't draining, drop the line.
  if ((size_t)Serial.availableForWrite() < n) {
    txDropped++;
    return;
  }
  Serial.write((const uint8_t*)s, n);
}

static void sendEvent(const char* e, const char* detail = "") {
  char b[160];
  sendLine(b, proto::fmtEvent(b, sizeof b, e, detail));
}

static void flushEvents() {
  for (int i = 0; i < events.size(); i++) sendEvent(events[i].e, events[i].detail);
  events.clear();
}

static void sendHello() {
  char b[160];
  const motion::Caps c = drive.compiledCaps();
  sendLine(b, proto::fmtHello(b, sizeof b, FW_VERSION, c.v_max, c.a_max, c.w_max));
}

// ---- servos ------------------------------------------------------------------------
static void servoError(ServoSlot& s, const char* what) {
  char d[40];
  snprintf(d, sizeof d, "id=%d %s", s.id, what);
  events.push("servo_error", d);
}

// The ONE place that decides whether a servo should have torque.
static bool wantTorque(const ServoSlot& s, uint32_t now) {
  if (!torqueWanted || s.faulted || !motorsOn) return false;
  // Tilt: the head goes limp at once; the wheels keep torque only while they
  // brake to zero (at most TILT_BRAKE_MAX_MS), then everything is limp.
  if (reflexes.tiltLatched()) return s.wheel && tiltBraking;
  return s.wheel ? drive.wheelTorqueWanted(now) : true;
}

// Torque OFF is always sent, even to a servo we think is offline (its reply
// line may be broken while it still hears us). Torque ON only to online ones.
static void setServoTorque(ServoSlot& s, bool on) {
  if (on && !s.online) return;
  if (on && !s.wheel && s.fb.ok) {
    // hold where it is rather than jump to a stale goal
    bus.goalPos(s.id, s.fb.pos, head::speedToSteps(HEAD_SPEED_DEFAULT_DPS, HEAD_SPEED_MAX_DPS,
                                                    HEAD_SPEED_DEFAULT_DPS),
                HEAD_ACC);
  }
  if (on && s.wheel) bus.WriteSpe(s.id, 0, WHEEL_ACC);  // never wake up with a stale speed
  const bool acked = bus.torque(s.id, on);
  if (acked) s.torque = on;
  else if (!on) s.torque = false;  // assume off; the readback will tell
}

// Safety broadcast: every servo limp + wheels at zero. No replies, cheap.
static void busSafeState() {
  uint8_t ids[2] = {SERVO_ID_LEFT, SERVO_ID_RIGHT};
  int16_t zero[2] = {0, 0};
  bus.syncSpeeds(ids, 2, zero, 0);
  bus.broadcastTorqueOff();
  for (auto& s : servos) s.torque = false;
}

static bool wheelTorqueBoth() { return servos[S_LEFT].torque && servos[S_RIGHT].torque; }

// Bring every servo's torque in line with wantTorque(); retried every tick.
static void reconcileTorque(uint32_t now) {
  for (auto& s : servos) {
    const bool want = wantTorque(s, now) && s.online;
    if (want != s.torque) setServoTorque(s, want);
  }
}

// Read reg 40 back (a brown-out resets a servo's SRAM) -- one servo per call.
static void verifyTorque() {
  static int next = 0;
  ServoSlot& s = servos[next];
  next = (next + 1) % 4;
  if (!s.online) return;
  const int t = bus.readReg8(s.id, 40);
  if (t >= 0) s.torque = (t == 1);
  // a reset servo also lost its torque limit (reg 48 = EEPROM reg 16 again);
  // reg 16 is written at init, so the limit survives a reset.
}

// Initialise one servo per call (keeps each control tick short).
static void initServo(ServoSlot& s) {
  s.fails = 0;
  s.errReported = false;
  s.faulted = false;
  if (!bus.ping(s.id)) {
    s.online = false;
    servoError(s, "no_reply");
    s.errReported = true;
    return;
  }
  s.online = true;
  bus.torque(s.id, false);  // start limp; reconcileTorque() decides afterwards
  s.torque = false;
  const int vmax = bus.readReg8(s.id, 14);
  if (vmax >= 0 && vmax < STS_MIN_VMAX_SETTING) {
    char d[40];
    snprintf(d, sizeof d, "vmax=%d.%dV(reg14)", vmax / 10, vmax % 10);
    servoError(s, d);
  }
  // Operating mode (EEPROM 33): 1 = wheel, 0 = position. Written only if it
  // differs, then read back. Unknown or wrong -> this servo never gets torque.
  const int wantMode = s.wheel ? 1 : 0;
  int mode = bus.readReg8(s.id, 33);
  if (mode >= 0 && mode != wantMode) {
    bus.writeEeprom8(s.id, 33, wantMode);
    mode = bus.readReg8(s.id, 33);
  }
  if (mode != wantMode) {
    s.faulted = true;
    servoError(s, mode < 0 ? "mode_unknown" : "mode_wrong");
    return;
  }
  // EEPROM plan (servo_cfg.cpp): torque ceiling (reg 16, survives resets),
  // protection current / torque / time, overload torque, and for pan/tilt the
  // angle limits. Each is written only if different, then READ BACK; a servo
  // that doesn't verify never gets torque.
  servo::RegSetting plan[8];
  const int np = servo::eepromPlan(s.kind, plan);
  for (int i = 0; i < np; i++) {
    const servo::RegSetting& r = plan[i];
    int v = r.size == 2 ? bus.readReg16(s.id, r.reg) : bus.readReg8(s.id, r.reg);
    if (v >= 0 && v != r.value) {
      if (r.size == 2) bus.writeEeprom16(s.id, r.reg, r.value);
      else bus.writeEeprom8(s.id, r.reg, (uint8_t)r.value);
      v = r.size == 2 ? bus.readReg16(s.id, r.reg) : bus.readReg8(s.id, r.reg);
    }
    if (v != r.value) {
      char d[40];
      snprintf(d, sizeof d, "verify_%s", r.name);
      s.faulted = true;
      servoError(s, d);
      return;
    }
  }
  // Unloading conditions (reg 19): current + overload protection must be on.
  int unload = bus.readReg8(s.id, 19);
  const int fix = servo::unloadingFix(unload);
  if (fix >= 0) {
    bus.writeEeprom8(s.id, 19, (uint8_t)fix);
    unload = bus.readReg8(s.id, 19);
  }
  if (unload < 0 || servo::unloadingFix(unload) >= 0) {
    s.faulted = true;
    servoError(s, "verify_unloading");
    return;
  }
  // SRAM torque limit for right now (reg 48), verified too.
  const uint16_t lim = servo::torqueLimit(s.kind);
  bus.writeReg16(s.id, 48, lim);
  if (bus.readReg16(s.id, 48) != lim) {
    s.faulted = true;
    servoError(s, "verify_torque_limit");
    return;
  }
  if (s.wheel) {
    bus.WriteSpe(s.id, 0, WHEEL_ACC);
  } else {
    bus.writeReg8(s.id, 41, HEAD_ACC);
    bus.feedback(s.id, s.fb);
    s.fbMs = millis();
  }
}

static void startServoInit(uint32_t now, uint32_t delayMs) {
  initStep = 0;
  initAtMs = now + delayMs;
}

static void servoInitTick(uint32_t now) {
  // Not before the reflexes run: a robot booted on its side must not get torque.
  if (!bootDone) return;
  if (initStep < 0 || initStep >= 4 || (int32_t)(now - initAtMs) < 0) return;
  if (initStep == 0) bus.detectEcho();
  initServo(servos[initStep]);
  initStep++;
  if (initStep == 4) {
    unwrapL.reset();
    unwrapR.reset();
  }
}

static bool servosReady() { return initStep == 4; }

// status bits that mean the servo is limiting or cutting its own torque
static const uint8_t kStatusTorqueFault = 0x2C;  // b2 temperature, b3 current, b5 overload

static bool wheelOk(const ServoSlot& s) {
  return s.online && !s.faulted && !(s.lastStatus & kStatusTorqueFault);
}
static bool wheelsOk() { return servosReady() && wheelOk(servos[S_LEFT]) && wheelOk(servos[S_RIGHT]); }

static void readFeedback(ServoSlot& s, uint32_t now) {
  if (!s.online) return;
  if (bus.feedback(s.id, s.fb)) {
    s.fails = 0;
    s.fbMs = now;
    const uint8_t st = (uint8_t)(s.fb.status & 0x3F);
    if (st && st != s.lastStatus) {
      char d[24];
      snprintf(d, sizeof d, "status=0x%02x", st);
      servoError(s, d);  // b0 V, b1 sensor, b2 temp, b3 current, b4 angle, b5 overload
    }
    s.lastStatus = st;
  } else if (++s.fails >= STS_FAIL_LIMIT) {
    s.online = false;
    setServoTorque(s, false);  // still sent: it may hear us even if it can't answer
    if (!s.errReported) servoError(s, "no_reply");
    s.errReported = true;
  }
}

static void applyHeadTarget() {
  if (!headPending || !servosReady() || !torqueWanted || reflexes.tiltLatched()) return;
  const int sp = head::speedToSteps(headSpeed, HEAD_SPEED_MAX_DPS, HEAD_SPEED_DEFAULT_DPS);
  ServoSlot& p = servos[S_PAN];
  ServoSlot& t = servos[S_TILT];
  if (p.online && p.torque) bus.goalPos(p.id, head::degToSteps(head::panAxis(), headPan), sp, HEAD_ACC);
  if (t.online && t.torque) bus.goalPos(t.id, head::degToSteps(head::tiltAxis(), headTilt), sp, HEAD_ACC);
  headPending = false;
}

// ---- commands ----------------------------------------------------------------------
static void handleLine(const char* line, uint32_t now) {
  proto::Command c;
  char b[160];
  switch (proto::parse(line, c)) {
    case proto::Type::Vel:
      drive.command(c.v, c.w, now);
      break;
    case proto::Type::Head:
      if (c.has_pan) headPan = head::clampDeg(head::panAxis(), c.pan);
      if (c.has_tilt) headTilt = head::clampDeg(head::tiltAxis(), c.tilt);
      headSpeed = c.has_speed ? c.speed : HEAD_SPEED_DEFAULT_DPS;
      headPending = true;
      applyHeadTarget();
      break;
    case proto::Type::Light:
      lightMode = c.mode;
      lightRgb = c.has_rgb ? led::Rgb{c.rgb[0], c.rgb[1], c.rgb[2]} : led::defaultColour(c.mode);
      break;
    case proto::Type::Stop:
      // brake to zero at A_ESTOP, hold STOP_BRAKE_MS, then coast
      // (Drive + reconcileTorque do it on the next ticks)
      drive.stopNow(now);
      break;
    case proto::Type::Torque:
      if (c.on) {
        if (reflexes.requestTorqueOn(now)) {
          torqueWanted = true;
          reconcileTorque(now);
        } else {
          sendEvent("tilt", "torque_on_refused");
        }
      } else {
        torqueWanted = false;
        headPending = false;  // never replay a stale head move later
        if (motorsOn) busSafeState();
        reconcileTorque(now);
      }
      break;
    case proto::Type::Limits: {
      const motion::Caps k = drive.setLimits(c.v_max, c.a_max, c.w_max);
      sendLine(b, proto::fmtLimits(b, sizeof b, k.v_max, k.a_max, k.w_max));
      break;
    }
    case proto::Type::Ping:
      sendLine(b, proto::fmtPong(b, sizeof b, c.id_json));
      break;
    case proto::Type::Cal:
      floorCal.start(now);
      calReplyPending = true;
      break;
    case proto::Type::Diag: {
      char d[768];
      int n = snprintf(d, sizeof d,
                       "{\"t\":\"diag\",\"fw\":\"%s\",\"imu\":\"%s\",\"imu_ok\":%s,\"loop_hz\":%lu,"
                       "\"bus_echo\":%s,\"bus_tx\":%lu,\"bus_rx_fail\":%lu,\"tof_alive\":%u,"
                       "\"floor_mm\":[%d,%d,%d],\"tx_dropped\":%lu,\"servos\":[",
                       FW_VERSION, imuDev.name(), imuDev.ok(now) ? "true" : "false",
                       (unsigned long)loopHz, bus.echo() ? "true" : "false",
                       (unsigned long)bus.txPackets, (unsigned long)bus.rxFailures,
                       (unsigned)tofs.aliveMask(), floorCal.floorMm(0), floorCal.floorMm(1),
                       floorCal.floorMm(2), (unsigned long)txDropped);
      for (int i = 0; i < 4 && n > 0 && n < (int)sizeof d; i++) {
        const ServoSlot& s = servos[i];
        n += snprintf(d + n, sizeof d - n,
                      "%s{\"id\":%d,\"online\":%s,\"torque\":%s,\"faulted\":%s,\"pos\":%d,"
                      "\"v_dv\":%d,\"temp\":%d,\"load\":%d,\"status\":%d}",
                      i ? "," : "", s.id, s.online ? "true" : "false", s.torque ? "true" : "false",
                      s.faulted ? "true" : "false", s.fb.pos, s.fb.voltage_dv, s.fb.temp_c, s.fb.load,
                      s.fb.status);
      }
      if (n > 0 && n < (int)sizeof d - 4) {
        n += snprintf(d + n, sizeof d - n, "]}\n");
        sendLine(d, n);
      }
      break;
    }
    case proto::Type::Unknown:
    case proto::Type::Invalid:
    default:
      break;  // ignored, never fatal
  }
}

static void readSerial(uint32_t now) {
  int budget = 512;  // bytes per pass, so a flood cannot starve the reflexes
  while (budget-- > 0 && Serial.available() > 0) {
    const int ch = Serial.read();
    if (ch < 0) break;
    if (rxLine.push((char)ch)) handleLine(rxLine.line(), now);
  }
}

// ---- sensors -----------------------------------------------------------------------
static float adcMv(int pin) {
  uint32_t sum = 0;
  for (int i = 0; i < 8; i++) sum += analogReadMilliVolts(pin);
  return sum / 8.0f;
}

static void pollTof(uint32_t now) {
  const int i = tofs.poll(now);
  if (i >= TOF_DOWN_L && i <= TOF_DOWN_R && floorCal.running()) {
    if (tofs[i].status == tof::RangeValid) floorCal.addSample(i, tofs[i].mm);
  }
}

static int fwdValue(int idx, uint32_t now) {
  const TofReading& r = tofs[idx];
  const int v = tof::forwardValue(r.status, r.mm, r.fresh(now, TOF_STALE_MS));
  return tof::bumperDistance(v, FWD_TOF_OFFSET_MM);
}

// ---- control tick (50 Hz) -------------------------------------------------------------
static uint32_t lastControlMs = 0;

static void controlTick(uint32_t now) {
  const float dt = lastControlMs ? (now - lastControlMs) / 1000.0f : CONTROL_PERIOD_MS / 1000.0f;
  lastControlMs = now;

  // Motor power (kill switch), read as an analogue rail voltage with
  // hysteresis -- a sagging pack must not read as "off" while the servos run.
  const float railV = analogReadMilliVolts(PIN_MOTOR_SENSE) * MOTOR_DIVIDER_RATIO / 1000.0f;
  if (railV > MOTOR_ON_V) motorRailHigh = true;
  else if (railV < MOTOR_OFF_V) motorRailHigh = false;
  const bool m = motorSense.update(motorRailHigh, now);
  if (m != motorsOn) {
    motorsOn = m;
    if (m) {
      startServoInit(now, 500);  // let the servos boot
    } else {
      initStep = -1;
      for (auto& s : servos) s.online = false;
    }
  }
  // While "off", keep telling the bus to be limp and still. Harmless if the
  // servos really are unpowered; essential if the sense reading is wrong.
  if (!motorsOn) busSafeState();
  servoInitTick(now);

  // Drop detection on the latest down-sensor readings.
  for (int i = 0; i < 3; i++) {
    const TofReading& r = tofs[i];
    dropDet[i].update(now, tof::downReadingOk(r.status, r.fresh(now, TOF_STALE_MS)), r.mm,
                      floorCal.floorMm(i));
  }
  if (floorCal.tick(now) && calReplyPending) {
    char b[96];
    int f[3];
    bool ok[3];
    for (int i = 0; i < 3; i++) f[i] = floorCal.floorMm(i), ok[i] = floorCal.lastOk(i);
    sendLine(b, proto::fmtCal(b, sizeof b, f, ok));
    calReplyPending = false;
  }

  // Boot: no reflex output until the IMU and the first floor calibration are done.
  if (!bootDone && !floorCal.running() && (imuDev.ready() || imuDev.failed() ||
                                           (now - bootStartMs) > 5000)) {
    bootDone = true;
  }

  motion::ReflexLimits lim;
  if (bootDone) {
    reflex::Inputs in;
    in.now_ms = now;
    in.bump_l = bumpL.state();
    in.bump_r = bumpR.state();
    for (int i = 0; i < 3; i++) in.drop[i] = dropDet[i].drop();
    in.fwd_mm[0] = fwdValue(TOF_FWD_L, now);
    in.fwd_mm[1] = fwdValue(TOF_FWD_R, now);
    in.imu_ok = imuDev.ok(now);
    in.roll_deg = imuDev.roll;
    in.pitch_deg = imuDev.pitch;
    in.ntc_ok = powerMon.ntcOk();
    in.pack_c = powerMon.packC();
    in.bat_v = powerMon.batV();
    in.motors_on = motorsOn;
    in.vel_fresh = drive.fresh(now);
    in.vel_ever = drive.everCommanded();
    in.wheels_ok = wheelsOk();
    lim = reflexes.update(in, events);
  } else {
    lim.block_all = true;
  }
  if (floorCal.running()) lim.block_all = true;  // never drive while calibrating

  const kin::WheelSpeeds ws = drive.tick(now, dt, lim);

  // Tilt: brake the wheels at A_ESTOP (head limp at once), then everything
  // limp until upright 2 s + `torque on`.
  if (lim.torque_kill && torqueWanted) {
    if (!tiltBraking) {
      tiltBraking = true;
      tiltT0 = now;
    }
    if ((ws.l == 0 && ws.r == 0) || (uint32_t)(now - tiltT0) >= TILT_BRAKE_MAX_MS) {
      tiltBraking = false;
      torqueWanted = false;
      headPending = false;
      if (motorsOn) busSafeState();
    }
  } else if (!lim.torque_kill) {
    tiltBraking = false;
  }

  if (servosReady() && motorsOn) {
    reconcileTorque(now);  // retries any servo whose torque state is wrong
    uint8_t ids[2] = {SERVO_ID_LEFT, SERVO_ID_RIGHT};
    int16_t sp[2] = {
        kin::clampSteps(LEFT_WHEEL_SIGN * kin::mpsToSteps(ws.l, WHEEL_DIAMETER_M, STS_STEPS_PER_REV),
                        STS_MAX_SPEED_STEPS),
        kin::clampSteps(RIGHT_WHEEL_SIGN * kin::mpsToSteps(ws.r, WHEEL_DIAMETER_M, STS_STEPS_PER_REV),
                        STS_MAX_SPEED_STEPS)};
    // Only drive when BOTH wheels have torque: one wheel alone would pivot.
    if (!wheelTorqueBoth() || !wheelsOk()) sp[0] = sp[1] = 0;
    bus.syncSpeeds(ids, 2, sp, WHEEL_ACC);  // sent every tick, also refreshes zero

    // odometry from present position (single-turn 0..4095, unwrapped)
    int32_t d;
    readFeedback(servos[S_LEFT], now);
    if (servos[S_LEFT].online && servos[S_LEFT].fbMs == now &&
        unwrapL.update(servos[S_LEFT].fb.pos, now, 500, STS_STEPS_PER_REV, d))
      totalL += LEFT_WHEEL_SIGN * d;
    readFeedback(servos[S_RIGHT], now);
    if (servos[S_RIGHT].online && servos[S_RIGHT].fbMs == now &&
        unwrapR.update(servos[S_RIGHT].fb.pos, now, 500, STS_STEPS_PER_REV, d))
      totalR += RIGHT_WHEEL_SIGN * d;

    // a servo that fell off the bus: try to bring it back once a second
    if ((now - lastRecoverMs) > 1000) {
      lastRecoverMs = now;
      for (auto& s : servos)
        if (!s.online && !s.faulted && bus.ping(s.id)) {
          initServo(s);
          if (s.wheel) (s.id == SERVO_ID_LEFT ? unwrapL : unwrapR).reset();
          break;
        }
    }
  }
  const float dl = kin::stepsToMeters((float)(totalL - odomL), WHEEL_DIAMETER_M, STS_STEPS_PER_REV);
  const float dr = kin::stepsToMeters((float)(totalR - odomR), WHEEL_DIAMETER_M, STS_STEPS_PER_REV);
  odomL = totalL;
  odomR = totalR;
  odom.update(dl, dr, dt);

  char b[160];
  sendLine(b, proto::fmtOdom(b, sizeof b, odom.x, odom.y, odom.th, odom.v, odom.w, now));
  sendLine(b, proto::fmtImu(b, sizeof b, imuDev.roll, imuDev.pitch, imuDev.yaw, imuDev.gz));
  flushEvents();
}

// ---- state tick (5 Hz) -------------------------------------------------------------
static void stateTick(uint32_t now) {
  powerMon.update(now, adcMv(PIN_ADC_BATTERY), adcMv(PIN_ADC_NTC), adcMv(PIN_ADC_CHARGE), events);
  if (servosReady() && motorsOn) {
    readFeedback(servos[S_PAN], now);
    readFeedback(servos[S_TILT], now);
    verifyTorque();
    applyHeadTarget();
  }
  // Retry dead ToFs only while standing still (the re-init blocks ~60 ms).
  const kin::WheelSpeeds ws = drive.current();
  if (ws.l == 0 && ws.r == 0) tofs.retryDead(now);

  proto::StateMsg s;
  s.bat_v = powerMon.batV();
  s.bat_pct = powerMon.pct();
  s.charging = powerMon.charging();
  s.on_dock = powerMon.onDock();
  s.pack_ok = powerMon.ntcOk();
  s.pack_c = powerMon.packC();
  s.bump[0] = bumpL.state();
  s.bump[1] = bumpR.state();
  for (int i = 0; i < 3; i++) s.drop[i] = dropDet[i].drop();
  s.fwd_mm[0] = fwdValue(TOF_FWD_L, now);
  s.fwd_mm[1] = fwdValue(TOF_FWD_R, now);
  const ServoSlot& p = servos[S_PAN];
  const ServoSlot& t = servos[S_TILT];
  s.pan_ok = p.online && p.fb.ok && (now - p.fbMs) < 1000;
  s.pan = head::stepsToDeg(head::panAxis(), p.fb.pos);
  s.tilt_ok = t.online && t.fb.ok && (now - t.fbMs) < 1000;
  s.tilt = head::stepsToDeg(head::tiltAxis(), t.fb.pos);
  s.motors = motorsOn;
  // during boot: calibrating -> "drop", waiting for the IMU -> "tilt"
  s.fault = bootDone ? reflexes.fault() : "tilt";
  if (floorCal.running()) s.fault = "drop";
  char b[400];
  sendLine(b, proto::fmtState(b, sizeof b, s));
  flushEvents();
}

static void ledTick(uint32_t now) {
  led::Rgb px[LED_COUNT];
  led::Mode m = lightMode;
  led::Rgb c = lightRgb;
  if (reflexes.packHot()) {  // reflex override: pack hot -> alert
    m = led::ALERT;
    c = led::defaultColour(led::ALERT);
  }
  led::render(m, c, now, powerMon.pct(), LED_MAX_BRIGHTNESS, px, LED_COUNT);
  for (int i = 0; i < LED_COUNT; i++) ring.setPixelColor(i, px[i].r, px[i].g, px[i].b);
  ring.show();  // ~0.5 ms for 16 LEDs
}

// ---- setup / loop -------------------------------------------------------------------
void setup() {
#if ARDUINO_USB_MODE
  Serial.setTxBufferSize(4096);
  Serial.setRxBufferSize(1024);
  Serial.setTxTimeoutMs(0);  // never block the loop on a slow or absent host
#endif
  Serial.begin(PI_BAUD);

  pinMode(PIN_BUMP_L, INPUT_PULLUP);
  pinMode(PIN_BUMP_R, INPUT_PULLUP);
  pinMode(PIN_MOTOR_SENSE, INPUT);  // analogue (ADC1_CH4)
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  ring.begin();
  ring.clear();
  ring.show();

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, 400000);
  Wire.setTimeOut(5);  // ms: a stuck device cannot hang the loop for long
  tofs.begin(Wire);
  imuDev.begin(Wire);

  bus.begin(Serial1, STS_BAUD, PIN_SERVO_RX, PIN_SERVO_TX, STS_BUS_ECHO);

  // First power sample before any reflex runs (avoids a false BMS-cutoff).
  powerMon.update(millis(), adcMv(PIN_ADC_BATTERY), adcMv(PIN_ADC_NTC), adcMv(PIN_ADC_CHARGE),
                  events);
  motorRailHigh = analogReadMilliVolts(PIN_MOTOR_SENSE) * MOTOR_DIVIDER_RATIO / 1000.0f > MOTOR_ON_V;
  motorSense.force(motorRailHigh);

  bootStartMs = millis();
  floorCal.start(bootStartMs);  // boot floor calibration (robot should be on the floor, still)
  calReplyPending = true;
  sendHello();
}

void loop() {
  static uint32_t lastBumpUs = 0, lastStateMs = 0, lastLedMs = 0;
  static bool wasConnected = false;
  const uint32_t now = millis();

  readSerial(now);

  const uint32_t us = micros();
  if ((uint32_t)(us - lastBumpUs) >= BUMP_SAMPLE_US) {
    lastBumpUs = us;
    bumpL.update(digitalRead(PIN_BUMP_L) == LOW, now);
    bumpR.update(digitalRead(PIN_BUMP_R) == LOW, now);
  }

  pollTof(now);
  imuDev.poll(now);

  // A new bumper press runs the control tick immediately (<= 1 ms + debounce).
  static bool lastBumpAny = false;
  const bool bumpAny = bumpL.state() || bumpR.state();
  const bool bumpEdge = bumpAny && !lastBumpAny;
  lastBumpAny = bumpAny;

  if ((uint32_t)(now - lastControlMs) >= CONTROL_PERIOD_MS || bumpEdge) controlTick(now);
  if ((uint32_t)(now - lastStateMs) >= STATE_PERIOD_MS) {
    lastStateMs = now;
    stateTick(now);
  }
  if ((uint32_t)(now - lastLedMs) >= LED_PERIOD_MS) {
    lastLedMs = now;
    ledTick(now);
  }

  // Re-announce when the host (re)opens the port.
  const bool connected = (bool)Serial;
  if (connected && !wasConnected) sendHello();
  wasConnected = connected;

  loopCount++;
  if ((uint32_t)(now - statWindowMs) >= 1000) {
    loopHz = loopCount;
    loopCount = 0;
    statWindowMs = now;
  }
}
