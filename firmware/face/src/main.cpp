// =============================================================================
//  Claude body -- FACE firmware. PROTOCOL.md section 2.
//
//  Eyes: procedural, drawn every frame from a pose (no bitmaps). The look:
//  big round Claude-orange irises with a warm highlight on black; eyelids
//  are black shapes that sweep over them. Moods blend smoothly, the eyes
//  blink on their own (sometimes twice) and make tiny idle glances.
//
//  Loop (never blocks for long): serial in -> touch -> visor -> ears ->
//  one display pipeline step (the SPI DMA runs in the background).
// =============================================================================
#include <Arduino.h>

#include "blink.h"
#include "config.h"
#include "debounce.h"
#include "ears.h"
#include "eye_geom.h"
#include "eyes.h"
#include "gesture.h"
#include "head_range.h"
#include "line_buffer.h"
#include "moods.h"
#include "pins.h"
#include "protocol.h"
#include "servo_pwm.h"
#include "visor.h"

static EyeDisplay eyes;
static HeadRange headRange;
static face::MoodBlender blender;
static face::Blinker blinker(face::defaultBlinkTiming(), 0);
static face::Ears ears(EAR_SLEW_PER_S, EAR_WIGGLE_MS, EAR_WIGGLE_HZ, EAR_WIGGLE_AMP);
static face::GestureDetector gestures(TOUCH_DEBOUNCE_MS, TOUCH_HOLD_MS, TOUCH_DOUBLE_GAP_MS);
static face::Visor visor(VISOR_OPEN_TIMEOUT_MS, VISOR_CLOSE_MS);
static Debouncer visorSw(VISOR_SW_DEBOUNCE_MS, VISOR_SW_DEBOUNCE_MS);
static ServoPwm visorServo, earServo[2];
static LineBuffer<PI_LINE_MAX> rxLine;

static float brightness = BRIGHT_DEFAULT;
static float gazeTarget[2] = {0, 0}, gaze[2] = {0, 0};
static float micro[2] = {0, 0};  // idle micro-glance offset
static uint32_t nextMicroMs = 0, lastGazeCmdMs = 0;
static uint32_t txDropped = 0;

static uint32_t rnd(uint32_t n) { return n ? esp_random() % n : 0; }

static void sendLine(const char* s, size_t n) {
  if (n == 0) return;
  if ((size_t)Serial.availableForWrite() < n) {  // never block on USB
    txDropped++;
    return;
  }
  Serial.write((const uint8_t*)s, n);
}

static void sendVisor() {
  char b[64];
  sendLine(b, face::fmtVisor(b, sizeof b, face::visorName(visor.report())));
}

static void sendHello() {
  char b[64];
  sendLine(b, face::fmtHello(b, sizeof b, FW_VERSION));
}

static void setMood(face::Mood m, uint32_t ms, uint32_t now) {
  const bool wasClosed = blender.at(now).closed;
  blender.set(m, now, ms);
  const face::FacePose& p = face::moodPose(m);
  ears.setTarget(p.ear[0], p.ear[1]);  // a mood resets any `ears` override
  if (p.wiggle) ears.wiggle(now);
  blinker.setAuto(!p.closed, now);
  // A blink now and then while changing expression looks natural.
  if (!p.closed && !wasClosed && ms >= 150 && rnd(100) < 40) blinker.trigger(now);
}

static void handleLine(const char* line, uint32_t now) {
  face::Command c;
  char b[384];
  switch (face::parse(line, c)) {
    case face::Type::Mood:
      setMood(c.mood, c.has_ms ? c.ms : MOOD_DEFAULT_MS, now);
      break;
    case face::Type::Gaze:
      gazeTarget[0] = c.x;
      gazeTarget[1] = c.y;
      lastGazeCmdMs = now;
      break;
    case face::Type::Blink:
      if (!face::moodPose(blender.mood()).closed) blinker.trigger(now);
      break;
    case face::Type::Ears:
      if (c.has_l || c.has_r)
        ears.setTarget(c.has_l ? c.l : ears.target(0), c.has_r ? c.r : ears.target(1));
      if (c.wiggle) ears.wiggle(now);
      break;
    case face::Type::Visor:
      visor.command(c.open, now);
      visor.takeChanged();
      sendVisor();  // always answer, even if nothing changed, so the Pi can resync
      break;
    case face::Type::Bright:
      brightness = c.b;
      break;
    case face::Type::Ping:
      sendLine(b, face::fmtPong(b, sizeof b, c.id_json));
      break;
    case face::Type::Diag: {
      const int n = snprintf(
          b, sizeof b,
          "{\"t\":\"diag\",\"fw\":\"%s\",\"fps\":%.1f,\"render_us\":%lu,\"psram_ok\":%s,"
          "\"psram_free\":%u,\"mood\":\"%s\",\"visor\":\"%s\",\"visor_sw\":%s,\"range_alive\":%s,\"tx_dropped\":%lu}\n",
          FW_VERSION, eyes.fps(), (unsigned long)eyes.renderUs(), eyes.psramOk() ? "true" : "false",
          (unsigned)ESP.getFreePsram(), face::moodName(blender.mood()),
          face::visorName(visor.report()), visorSw.state() ? "true" : "false",
          headRange.alive() ? "true" : "false", (unsigned long)txDropped);
      if (n > 0 && n < (int)sizeof b) sendLine(b, n);
      break;
    }
    default:
      break;  // unknown / invalid: ignored
  }
}

static void readSerial(uint32_t now) {
  int budget = 512;
  while (budget-- > 0 && Serial.available() > 0) {
    const int ch = Serial.read();
    if (ch < 0) break;
    if (rxLine.push((char)ch)) handleLine(rxLine.line(), now);
  }
}

static void updateGaze(uint32_t now, float dt) {
  // Idle micro-glances: tiny, occasional, only when the Pi isn't steering.
  if ((int32_t)(now - nextMicroMs) >= 0) {
    nextMicroMs = now + 1500 + rnd(2500);
    const bool idle = (now - lastGazeCmdMs) > 3000;
    micro[0] = idle ? ((float)rnd(1000) / 1000.0f - 0.5f) * 0.12f : 0;
    micro[1] = idle ? ((float)rnd(1000) / 1000.0f - 0.5f) * 0.08f : 0;
  }
  const float k = 1.0f - expf(-dt * 1000.0f / GAZE_TAU_MS);
  for (int i = 0; i < 2; i++) gaze[i] += (gazeTarget[i] + micro[i] - gaze[i]) * k;
}

static void composeFrame(uint32_t now) {
  const face::FacePose p = blender.at(now);
  const float blink = p.closed ? 0 : blinker.closure(now);
  // very slight "alive" breathing of the iris size
  const float scale = 1.0f + 0.012f * sinf(6.2831853f * (float)(now % 4000) / 4000.0f);
  face::EyeGeom g[2];
  for (int e = 0; e < 2; e++)
    g[e] = face::eyeGeometry(p.eye[e], gaze[0], gaze[1], blink, e, scale, EYE_SIZE, GAZE_MAX_X_PX,
                             GAZE_MAX_Y_PX);
  eyes.setFrame(g, p.closed);

  float bl = brightness;
  if (p.closed) {  // asleep: slow breathing glow
    const float ph = (float)(now % BREATH_PERIOD_MS) / BREATH_PERIOD_MS;
    const float w = 0.5f - 0.5f * cosf(6.2831853f * ph);
    bl *= BREATH_MIN + (BREATH_MAX - BREATH_MIN) * w;
  }
  eyes.setBacklight(bl);
}

void setup() {
  // Visor DOWN first, before anything else can go wrong.
  visorServo.attach(PIN_VISOR_SERVO, VISOR_CLOSED_US);
  pinMode(PIN_VISOR_UP_SW, INPUT_PULLUP);
  pinMode(PIN_TOUCH, INPUT);

#if ARDUINO_USB_MODE
  Serial.setTxBufferSize(2048);
  Serial.setRxBufferSize(1024);
  Serial.setTxTimeoutMs(0);
#endif
  Serial.begin(PI_BAUD);

  const uint32_t now = millis();
  visor.boot(now);
  earServo[0].attach(PIN_EAR_LEFT, (EAR_L_DOWN_US + EAR_L_UP_US) / 2);
  earServo[1].attach(PIN_EAR_RIGHT, (EAR_R_DOWN_US + EAR_R_UP_US) / 2);

  eyes.begin();  // if PSRAM failed the eyes stay dark; `diag` reports psram_ok:false
  headRange.begin();  // a missing sensor just reports head_mm -1
  blinker.start(now);
  setMood(face::NEUTRAL, 0, now);

  sendHello();
  sendVisor();
  visor.takeChanged();
}

void loop() {
  static uint32_t lastMs = millis(), lastFrameMs = 0;
  static bool wasConnected = false;
  const uint32_t now = millis();
  const float dt = (now - lastMs) / 1000.0f;
  lastMs = now;

  readSerial(now);

  // Touch gestures
  const bool touch = (digitalRead(PIN_TOUCH) == HIGH) == (TOUCH_ACTIVE_HIGH != 0);
  for (face::Gesture g = gestures.update(touch, now); g != face::G_NONE;
       g = gestures.pending() ? gestures.update(touch, now) : face::G_NONE) {
    char b[48];
    sendLine(b, face::fmtTouch(b, sizeof b, face::gestureName(g)));
  }

  // Visor
  const bool up = visorSw.update(digitalRead(PIN_VISOR_UP_SW) == LOW, now);
  visor.update(up, now);
  visorServo.moveTo(visor.servoOpen() ? VISOR_OPEN_US : VISOR_CLOSED_US, VISOR_MOVE_MS, now);
  visorServo.update(now);
  if (visor.takeChanged()) sendVisor();

  // Ears
  float e[2];
  ears.update(now, e);
  earServo[0].set(EAR_L_DOWN_US + (EAR_L_UP_US - EAR_L_DOWN_US) * e[0]);
  earServo[1].set(EAR_R_DOWN_US + (EAR_R_UP_US - EAR_R_DOWN_US) * e[1]);

  // Head-height range: poll, report at 10 Hz
  static uint32_t lastRangeMs = 0;
  headRange.poll(now);
  if ((uint32_t)(now - lastRangeMs) >= RANGE_REPORT_MS) {
    lastRangeMs = now;
    char rb[48];
    sendLine(rb, face::fmtRange(rb, sizeof rb, headRange.value(now)));
  }

  // Eyes: compose a new frame when the pipeline is idle (frame-rate capped)
  updateGaze(now, dt);
  if (eyes.idle()) {
    if ((uint32_t)(now - lastFrameMs) >= FRAME_MIN_MS) {
      lastFrameMs = now;
      composeFrame(now);
      eyes.step(now);  // starts drawing the left eye
    }
  } else {
    eyes.step(now);  // continue: send left / draw right / send right
  }

  const bool connected = (bool)Serial;
  if (connected && !wasConnected) {
    sendHello();
    sendVisor();
  }
  wasConnected = connected;
}
