#include "protocol.h"

#include "config.h"

#include <ArduinoJson.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

namespace face {

static bool isNum(JsonVariantConst v) { return (v.is<float>() || v.is<long>()) && !v.is<bool>(); }
static float clampf(float x, float lo, float hi) { return x < lo ? lo : (x > hi ? hi : x); }

Type parse(const char* line, Command& c) {
  c = Command();
  JsonDocument doc;
  if (deserializeJson(doc, line) != DeserializationError::Ok || !doc.is<JsonObject>())
    return c.type = Type::Invalid;
  const char* t = doc["t"].as<const char*>();
  if (!t) return c.type = Type::Invalid;

  if (strcmp(t, "mood") == 0) {
    if (!moodFromName(doc["m"].as<const char*>(), c.mood)) return c.type = Type::Invalid;
    if (isNum(doc["ms"])) {
      const float ms = doc["ms"].as<float>();
      if (isfinite(ms)) {
        c.has_ms = true;
        c.ms = (uint32_t)clampf(ms, 0, 10000);
      }
    }
    return c.type = Type::Mood;
  }
  if (strcmp(t, "gaze") == 0) {
    if (!isNum(doc["x"]) || !isNum(doc["y"])) return c.type = Type::Invalid;
    const float x = doc["x"].as<float>(), y = doc["y"].as<float>();
    if (!isfinite(x) || !isfinite(y)) return c.type = Type::Invalid;
    c.x = clampf(x, -1, 1);
    c.y = clampf(y, -1, 1);
    return c.type = Type::Gaze;
  }
  if (strcmp(t, "blink") == 0) return c.type = Type::Blink;
  if (strcmp(t, "ears") == 0) {
    if (isNum(doc["l"])) c.has_l = true, c.l = clampf(doc["l"].as<float>(), 0, 1);
    if (isNum(doc["r"])) c.has_r = true, c.r = clampf(doc["r"].as<float>(), 0, 1);
    if (c.has_l && !isfinite(c.l)) c.has_l = false;
    if (c.has_r && !isfinite(c.r)) c.has_r = false;
    c.wiggle = doc["wiggle"].is<bool>() && doc["wiggle"].as<bool>();
    if (!c.has_l && !c.has_r && !c.wiggle) return c.type = Type::Invalid;
    return c.type = Type::Ears;
  }
  if (strcmp(t, "visor") == 0) {
    if (!doc["open"].is<bool>()) return c.type = Type::Invalid;
    c.open = doc["open"].as<bool>();
    return c.type = Type::Visor;
  }
  if (strcmp(t, "bright") == 0) {
    if (!isNum(doc["b"])) return c.type = Type::Invalid;
    const float b = doc["b"].as<float>();
    if (!isfinite(b)) return c.type = Type::Invalid;
    c.b = clampf(b, 0, 1);
    return c.type = Type::Bright;
  }
  if (strcmp(t, "ping") == 0) {
    JsonVariantConst id = doc["id"];
    if (!id.isNull() && measureJson(id) < sizeof(c.id_json))
      serializeJson(id, c.id_json, sizeof(c.id_json));
    return c.type = Type::Ping;
  }
  if (strcmp(t, "diag") == 0) return c.type = Type::Diag;
  return c.type = Type::Unknown;
}

static size_t finish(int r, size_t n) { return (r > 0 && (size_t)r < n) ? (size_t)r : 0; }

// The strings passed below are always our own constants (no escaping needed).
size_t fmtVisor(char* b, size_t n, const char* state) {
  return finish(snprintf(b, n, "{\"t\":\"visor\",\"state\":\"%s\"}\n", state), n);
}
size_t fmtTouch(char* b, size_t n, const char* g) {
  return finish(snprintf(b, n, "{\"t\":\"touch\",\"g\":\"%s\"}\n", g), n);
}
size_t fmtHello(char* b, size_t n, const char* fw) {
  return finish(snprintf(b, n, "{\"t\":\"hello\",\"fw\":\"%s\"}\n", fw), n);
}
size_t fmtRange(char* b, size_t n, int head_mm) {
  return finish(snprintf(b, n, "{\"t\":\"range\",\"head_mm\":%d}\n", head_mm), n);
}

int headRangeValue(bool alive, bool fresh, uint8_t status, int mm) {
  if (!alive || !fresh) return -1;
  switch (status) {
    case 0:  // RangeValid
    case 1:  // SigmaFail: noisy but a target estimate -> err towards caution
      if (mm < 0) mm = 0;
      return mm > RANGE_CLEAR_MM ? RANGE_CLEAR_MM : mm;
    case 3:   // RangeValidMinRangeClipped
    case 13:  // MinRangeFail
      return 0;
    case 2:  // SignalFail
    case 4:  // OutOfBoundsFail
    case 7:  // WrapTargetFail
    case 9:  // XtalkSignalFail
      return RANGE_CLEAR_MM;
    default:
      return -1;
  }
}

size_t fmtPong(char* b, size_t n, const char* id_json) {
  return finish(snprintf(b, n, "{\"t\":\"pong\",\"id\":%s}\n", id_json ? id_json : "null"), n);
}

}  // namespace face
