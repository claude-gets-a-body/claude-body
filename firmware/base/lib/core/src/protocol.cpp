#include "protocol.h"

#include <ArduinoJson.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

namespace proto {

static float num(JsonVariantConst v) { return v.as<float>(); }
static bool isNum(JsonVariantConst v) {
  return (v.is<float>() || v.is<long>()) && !v.is<bool>();
}
static float fin(float x) { return isfinite(x) ? x : 0.0f; }

Type parse(const char* line, Command& c) {
  c = Command();
  JsonDocument doc;
  if (deserializeJson(doc, line) != DeserializationError::Ok) return c.type = Type::Invalid;
  if (!doc.is<JsonObject>()) return c.type = Type::Invalid;
  const char* t = doc["t"].as<const char*>();
  if (!t) return c.type = Type::Invalid;

  if (strcmp(t, "vel") == 0) {
    if (!isNum(doc["v"]) || !isNum(doc["w"])) return c.type = Type::Invalid;
    c.v = num(doc["v"]);
    c.w = num(doc["w"]);
    if (!isfinite(c.v) || !isfinite(c.w)) return c.type = Type::Invalid;
    if (isNum(doc["seq"])) {
      c.has_seq = true;
      c.seq = doc["seq"].as<int32_t>();
    }
    return c.type = Type::Vel;
  }
  if (strcmp(t, "head") == 0) {
    if (isNum(doc["pan"])) c.has_pan = true, c.pan = num(doc["pan"]);
    if (isNum(doc["tilt"])) c.has_tilt = true, c.tilt = num(doc["tilt"]);
    if (isNum(doc["speed"])) c.has_speed = true, c.speed = num(doc["speed"]);
    if (!c.has_pan && !c.has_tilt) return c.type = Type::Invalid;
    return c.type = Type::Head;
  }
  if (strcmp(t, "light") == 0) {
    if (!led::modeFromName(doc["mode"].as<const char*>(), c.mode)) return c.type = Type::Invalid;
    JsonArrayConst rgb = doc["rgb"].as<JsonArrayConst>();
    if (!rgb.isNull() && rgb.size() == 3) {
      bool ok = true;
      for (int i = 0; i < 3; i++) {
        if (!isNum(rgb[i])) ok = false;
        else {
          float x = num(rgb[i]);
          x = x < 0 ? 0 : (x > 255 ? 255 : x);
          c.rgb[i] = (uint8_t)lroundf(x);
        }
      }
      c.has_rgb = ok;
    }
    return c.type = Type::Light;
  }
  if (strcmp(t, "stop") == 0) return c.type = Type::Stop;
  if (strcmp(t, "torque") == 0) {
    if (!doc["on"].is<bool>()) return c.type = Type::Invalid;
    c.on = doc["on"].as<bool>();
    return c.type = Type::Torque;
  }
  if (strcmp(t, "limits") == 0) {
    c.v_max = isNum(doc["v_max"]) ? num(doc["v_max"]) : NAN;
    c.a_max = isNum(doc["a_max"]) ? num(doc["a_max"]) : NAN;
    c.w_max = isNum(doc["w_max"]) ? num(doc["w_max"]) : NAN;
    return c.type = Type::Limits;
  }
  if (strcmp(t, "ping") == 0) {
    JsonVariantConst id = doc["id"];
    if (!id.isNull() && measureJson(id) < sizeof(c.id_json)) serializeJson(id, c.id_json, sizeof(c.id_json));
    return c.type = Type::Ping;
  }
  if (strcmp(t, "cal") == 0) return c.type = Type::Cal;
  if (strcmp(t, "diag") == 0) return c.type = Type::Diag;
  return c.type = Type::Unknown;
}

static size_t finish(int r, size_t n) { return (r > 0 && (size_t)r < n) ? (size_t)r : 0; }
static const char* tf(bool b) { return b ? "true" : "false"; }

size_t fmtOdom(char* b, size_t n, float x, float y, float th, float v, float w, uint32_t ts) {
  return finish(snprintf(b, n,
                         "{\"t\":\"odom\",\"x\":%.4f,\"y\":%.4f,\"th\":%.4f,\"v\":%.3f,\"w\":%.3f,"
                         "\"ts\":%lu}\n",
                         fin(x), fin(y), fin(th), fin(v), fin(w), (unsigned long)ts),
                n);
}

size_t fmtImu(char* b, size_t n, float roll, float pitch, float yaw, float gz) {
  return finish(snprintf(b, n,
                         "{\"t\":\"imu\",\"roll\":%.2f,\"pitch\":%.2f,\"yaw\":%.2f,\"gz\":%.2f}\n",
                         fin(roll), fin(pitch), fin(yaw), fin(gz)),
                n);
}

size_t fmtState(char* b, size_t n, const StateMsg& s) {
  char pack[16], pan[16], tilt[16], fault[32];
  if (s.pack_ok) snprintf(pack, sizeof pack, "%.1f", fin(s.pack_c));
  else strcpy(pack, "null");
  if (s.pan_ok) snprintf(pan, sizeof pan, "%.1f", fin(s.pan));
  else strcpy(pan, "null");
  if (s.tilt_ok) snprintf(tilt, sizeof tilt, "%.1f", fin(s.tilt));
  else strcpy(tilt, "null");
  if (s.fault) {
    char esc[24];
    jsonEscape(s.fault, esc, sizeof esc);
    snprintf(fault, sizeof fault, "\"%s\"", esc);
  } else {
    strcpy(fault, "null");
  }
  return finish(
      snprintf(b, n,
               "{\"t\":\"state\",\"bat_v\":%.2f,\"bat_pct\":%d,\"charging\":%s,\"on_dock\":%s,"
               "\"pack_c\":%s,\"bump\":[%s,%s],\"drop\":[%s,%s,%s],\"fwd_mm\":[%d,%d],"
               "\"pan\":%s,\"tilt\":%s,\"motors\":%s,\"fault\":%s}\n",
               fin(s.bat_v), s.bat_pct, tf(s.charging), tf(s.on_dock), pack, tf(s.bump[0]),
               tf(s.bump[1]), tf(s.drop[0]), tf(s.drop[1]), tf(s.drop[2]), s.fwd_mm[0],
               s.fwd_mm[1], pan, tilt, tf(s.motors), fault),
      n);
}

size_t fmtEvent(char* b, size_t n, const char* e, const char* detail) {
  char ee[24], dd[64];
  jsonEscape(e, ee, sizeof ee);
  if (detail && *detail) {
    jsonEscape(detail, dd, sizeof dd);
    return finish(snprintf(b, n, "{\"t\":\"event\",\"e\":\"%s\",\"detail\":\"%s\"}\n", ee, dd), n);
  }
  return finish(snprintf(b, n, "{\"t\":\"event\",\"e\":\"%s\"}\n", ee), n);
}

size_t fmtHello(char* b, size_t n, const char* fw, float v_max, float a_max, float w_max) {
  char f[40];
  jsonEscape(fw, f, sizeof f);
  return finish(snprintf(b, n,
                         "{\"t\":\"hello\",\"fw\":\"%s\",\"caps\":{\"v_max\":%.3f,\"a_max\":%.3f,"
                         "\"w_max\":%.3f}}\n",
                         f, fin(v_max), fin(a_max), fin(w_max)),
                n);
}

size_t fmtPong(char* b, size_t n, const char* id_json) {
  return finish(snprintf(b, n, "{\"t\":\"pong\",\"id\":%s}\n", id_json ? id_json : "null"), n);
}

size_t fmtCal(char* b, size_t n, const int f[3], const bool ok[3]) {
  return finish(snprintf(b, n, "{\"t\":\"cal\",\"floor_mm\":[%d,%d,%d],\"ok\":[%s,%s,%s]}\n", f[0],
                         f[1], f[2], tf(ok[0]), tf(ok[1]), tf(ok[2])),
                n);
}

size_t fmtLimits(char* b, size_t n, float v_max, float a_max, float w_max) {
  return finish(snprintf(b, n, "{\"t\":\"limits\",\"v_max\":%.3f,\"a_max\":%.3f,\"w_max\":%.3f}\n",
                         fin(v_max), fin(a_max), fin(w_max)),
                n);
}

void jsonEscape(const char* s, char* d, size_t n) {
  size_t o = 0;
  if (!n) return;
  for (; s && *s && o + 1 < n; s++) {
    const unsigned char ch = (unsigned char)*s;
    if (ch == '"' || ch == '\\') {
      if (o + 2 >= n) break;
      d[o++] = '\\';
      d[o++] = (char)ch;
    } else if (ch < 0x20) {
      if (o + 6 >= n) break;
      o += snprintf(d + o, n - o, "\\u%04x", ch);
    } else {
      d[o++] = (char)ch;
    }
  }
  d[o] = 0;
}

}  // namespace proto
