#include <ArduinoJson.h>
#include <math.h>
#include <string.h>
#include <unity.h>

#include "line_buffer.h"
#include "protocol.h"

using namespace proto;

void setUp() {}
void tearDown() {}

void test_parse_vel() {
  Command c;
  TEST_ASSERT_EQUAL(Type::Vel, parse("{\"t\":\"vel\",\"v\":0.1,\"w\":-0.5,\"seq\":42}", c));
  TEST_ASSERT_FLOAT_WITHIN(1e-6, 0.1f, c.v);
  TEST_ASSERT_FLOAT_WITHIN(1e-6, -0.5f, c.w);
  TEST_ASSERT_TRUE(c.has_seq);
  TEST_ASSERT_EQUAL(42, c.seq);
  TEST_ASSERT_EQUAL(Type::Vel, parse("{\"t\":\"vel\",\"v\":0,\"w\":1}", c));  // integers ok
  TEST_ASSERT_FALSE(c.has_seq);
  TEST_ASSERT_EQUAL(Type::Invalid, parse("{\"t\":\"vel\",\"v\":0.1}", c));  // w missing
  TEST_ASSERT_EQUAL(Type::Invalid, parse("{\"t\":\"vel\",\"v\":\"fast\",\"w\":0}", c));
  TEST_ASSERT_EQUAL(Type::Invalid, parse("{\"t\":\"vel\",\"v\":true,\"w\":0}", c));
}

void test_parse_head() {
  Command c;
  TEST_ASSERT_EQUAL(Type::Head, parse("{\"t\":\"head\",\"pan\":30,\"tilt\":-10.5,\"speed\":90}", c));
  TEST_ASSERT_TRUE(c.has_pan && c.has_tilt && c.has_speed);
  TEST_ASSERT_FLOAT_WITHIN(1e-6, -10.5f, c.tilt);
  TEST_ASSERT_EQUAL(Type::Head, parse("{\"t\":\"head\",\"tilt\":20}", c));
  TEST_ASSERT_FALSE(c.has_pan);
  TEST_ASSERT_EQUAL(Type::Invalid, parse("{\"t\":\"head\",\"speed\":20}", c));
}

void test_parse_light() {
  Command c;
  TEST_ASSERT_EQUAL(Type::Light, parse("{\"t\":\"light\",\"mode\":\"think\"}", c));
  TEST_ASSERT_EQUAL(led::THINK, c.mode);
  TEST_ASSERT_FALSE(c.has_rgb);
  TEST_ASSERT_EQUAL(Type::Light, parse("{\"t\":\"light\",\"mode\":\"idle\",\"rgb\":[300,-4,128]}", c));
  TEST_ASSERT_TRUE(c.has_rgb);
  TEST_ASSERT_EQUAL_UINT8(255, c.rgb[0]);
  TEST_ASSERT_EQUAL_UINT8(0, c.rgb[1]);
  TEST_ASSERT_EQUAL_UINT8(128, c.rgb[2]);
  TEST_ASSERT_EQUAL(Type::Light, parse("{\"t\":\"light\",\"mode\":\"idle\",\"rgb\":[1,2]}", c));
  TEST_ASSERT_FALSE(c.has_rgb);
  TEST_ASSERT_EQUAL(Type::Invalid, parse("{\"t\":\"light\",\"mode\":\"disco\"}", c));
  const char* modes[] = {"off", "idle", "listen", "think", "speak", "alert", "sleep", "charge"};
  for (int i = 0; i < 8; i++) {
    char line[64];
    snprintf(line, sizeof line, "{\"t\":\"light\",\"mode\":\"%s\"}", modes[i]);
    TEST_ASSERT_EQUAL(Type::Light, parse(line, c));
    TEST_ASSERT_EQUAL(i, (int)c.mode);
  }
}

void test_parse_simple_types() {
  Command c;
  TEST_ASSERT_EQUAL(Type::Stop, parse("{\"t\":\"stop\"}", c));
  TEST_ASSERT_EQUAL(Type::Torque, parse("{\"t\":\"torque\",\"on\":false}", c));
  TEST_ASSERT_FALSE(c.on);
  TEST_ASSERT_EQUAL(Type::Torque, parse("{\"t\":\"torque\",\"on\":true}", c));
  TEST_ASSERT_TRUE(c.on);
  TEST_ASSERT_EQUAL(Type::Invalid, parse("{\"t\":\"torque\",\"on\":1}", c));
  TEST_ASSERT_EQUAL(Type::Cal, parse("{\"t\":\"cal\"}", c));
  TEST_ASSERT_EQUAL(Type::Diag, parse("{\"t\":\"diag\"}", c));
}

void test_parse_limits_partial() {
  Command c;
  TEST_ASSERT_EQUAL(Type::Limits, parse("{\"t\":\"limits\",\"v_max\":0.1}", c));
  TEST_ASSERT_FLOAT_WITHIN(1e-6, 0.1f, c.v_max);
  TEST_ASSERT_TRUE(isnan(c.a_max));
  TEST_ASSERT_TRUE(isnan(c.w_max));
}

void test_parse_ping_ids() {
  Command c;
  TEST_ASSERT_EQUAL(Type::Ping, parse("{\"t\":\"ping\",\"id\":17}", c));
  TEST_ASSERT_EQUAL_STRING("17", c.id_json);
  TEST_ASSERT_EQUAL(Type::Ping, parse("{\"t\":\"ping\",\"id\":\"a\\\"b\"}", c));
  TEST_ASSERT_EQUAL_STRING("\"a\\\"b\"", c.id_json);
  TEST_ASSERT_EQUAL(Type::Ping, parse("{\"t\":\"ping\"}", c));
  TEST_ASSERT_EQUAL_STRING("null", c.id_json);
}

void test_unknown_and_garbage_are_ignored() {
  Command c;
  TEST_ASSERT_EQUAL(Type::Unknown, parse("{\"t\":\"dance\",\"style\":\"waltz\"}", c));
  TEST_ASSERT_EQUAL(Type::Invalid, parse("not json", c));
  TEST_ASSERT_EQUAL(Type::Invalid, parse("{\"v\":1}", c));
  TEST_ASSERT_EQUAL(Type::Invalid, parse("[1,2,3]", c));
  TEST_ASSERT_EQUAL(Type::Invalid, parse("{\"t\":\"vel\",\"v\":0.1,\"w\":0", c));  // truncated
  TEST_ASSERT_EQUAL(Type::Invalid, parse("", c));
}

// Every formatter must produce one valid JSON object per line.
static JsonDocument reparse(const char* line, size_t len) {
  TEST_ASSERT_TRUE(len > 0);
  TEST_ASSERT_EQUAL_CHAR('\n', line[len - 1]);
  TEST_ASSERT_NULL(memchr(line, '\n', len - 1));
  JsonDocument d;
  TEST_ASSERT_EQUAL(DeserializationError::Ok, deserializeJson(d, line).code());
  return d;
}

void test_format_odom_imu() {
  char b[256];
  size_t n = fmtOdom(b, sizeof b, 1.23456f, -0.5f, 3.1f, 0.2f, NAN, 123456);
  JsonDocument d = reparse(b, n);
  TEST_ASSERT_EQUAL_STRING("odom", d["t"]);
  TEST_ASSERT_FLOAT_WITHIN(1e-4, 1.2346f, d["x"].as<float>());
  TEST_ASSERT_EQUAL_FLOAT(0, d["w"].as<float>());  // NaN never reaches the wire
  TEST_ASSERT_EQUAL(123456, d["ts"].as<long>());
  n = fmtImu(b, sizeof b, 1.5f, -2.25f, 179.9f, -12.0f);
  d = reparse(b, n);
  TEST_ASSERT_EQUAL_STRING("imu", d["t"]);
  TEST_ASSERT_FLOAT_WITHIN(1e-3, -2.25f, d["pitch"].as<float>());
  TEST_ASSERT_TRUE(d["gz"].is<float>());
}

void test_format_state() {
  char b[512];
  StateMsg s;
  s.bat_v = 11.47f;
  s.bat_pct = 62;
  s.on_dock = true;
  s.pack_ok = true;
  s.pack_c = 31.2f;
  s.bump[1] = true;
  s.drop[0] = true;
  s.fwd_mm[0] = 345;
  s.fwd_mm[1] = 4000;
  s.pan_ok = true;
  s.pan = -12.3f;
  s.motors = true;
  s.fault = "bump";
  size_t n = fmtState(b, sizeof b, s);
  JsonDocument d = reparse(b, n);
  TEST_ASSERT_EQUAL_STRING("state", d["t"]);
  TEST_ASSERT_EQUAL(62, d["bat_pct"].as<int>());
  TEST_ASSERT_TRUE(d["on_dock"].as<bool>());
  TEST_ASSERT_FALSE(d["charging"].as<bool>());
  TEST_ASSERT_TRUE(d["bump"][1].as<bool>());
  TEST_ASSERT_TRUE(d["drop"][0].as<bool>());
  TEST_ASSERT_EQUAL(3, d["drop"].size());
  TEST_ASSERT_EQUAL(4000, d["fwd_mm"][1].as<int>());
  TEST_ASSERT_TRUE(d["tilt"].isNull());  // unread -> null
  TEST_ASSERT_EQUAL_STRING("bump", d["fault"]);
  s.fault = nullptr;
  s.pack_ok = false;
  d = reparse(b, fmtState(b, sizeof b, s));
  TEST_ASSERT_TRUE(d["fault"].isNull());
  TEST_ASSERT_TRUE(d["pack_c"].isNull());
  TEST_ASSERT_EQUAL(0u, fmtState(b, 40, s));  // too small: dropped, not truncated
}

void test_format_event_hello_pong_cal() {
  char b[256];
  JsonDocument d = reparse(b, fmtEvent(b, sizeof b, "obstacle", "l 99mm"));
  TEST_ASSERT_EQUAL_STRING("event", d["t"]);
  TEST_ASSERT_EQUAL_STRING("obstacle", d["e"]);
  TEST_ASSERT_EQUAL_STRING("l 99mm", d["detail"]);
  d = reparse(b, fmtEvent(b, sizeof b, "watchdog", ""));
  TEST_ASSERT_TRUE(d["detail"].isNull());
  d = reparse(b, fmtEvent(b, sizeof b, "servo_error", "id=1 \"odd\"\n"));
  TEST_ASSERT_EQUAL_STRING("id=1 \"odd\"\n", d["detail"]);
  d = reparse(b, fmtHello(b, sizeof b, "base 0.1.0", 0.25f, 0.5f, 1.5f));
  TEST_ASSERT_EQUAL_STRING("hello", d["t"]);
  TEST_ASSERT_FLOAT_WITHIN(1e-6, 0.25f, d["caps"]["v_max"].as<float>());
  TEST_ASSERT_FLOAT_WITHIN(1e-6, 1.5f, d["caps"]["w_max"].as<float>());
  d = reparse(b, fmtPong(b, sizeof b, "\"x\""));
  TEST_ASSERT_EQUAL_STRING("x", d["id"]);
  int f[3] = {31, 33, 35};
  bool ok[3] = {true, false, true};
  d = reparse(b, fmtCal(b, sizeof b, f, ok));
  TEST_ASSERT_EQUAL(33, d["floor_mm"][1].as<int>());
  TEST_ASSERT_FALSE(d["ok"][1].as<bool>());
  d = reparse(b, fmtLimits(b, sizeof b, 0.1f, 0.5f, 1.5f));
  TEST_ASSERT_FLOAT_WITHIN(1e-6, 0.1f, d["v_max"].as<float>());
}

void test_line_buffer() {
  LineBuffer<16> lb;
  const char* in = "{\"a\":1}\r\n\n{\"b\":2}\n";
  int lines = 0;
  for (const char* p = in; *p; p++) {
    if (lb.push(*p)) {
      lines++;
      TEST_ASSERT_EQUAL_CHAR('{', lb.line()[0]);
      TEST_ASSERT_EQUAL('}', lb.line()[lb.length() - 1]);
    }
  }
  TEST_ASSERT_EQUAL(2, lines);  // empty line skipped, CR stripped
  // over-long line is dropped whole, the next one still parses
  const char* lng = "0123456789abcdefXYZ\nok\n";
  lines = 0;
  for (const char* p = lng; *p; p++)
    if (lb.push(*p)) {
      lines++;
      TEST_ASSERT_EQUAL_STRING("ok", lb.line());
    }
  TEST_ASSERT_EQUAL(1, lines);
  TEST_ASSERT_EQUAL(1u, lb.overflows());
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_parse_vel);
  RUN_TEST(test_parse_head);
  RUN_TEST(test_parse_light);
  RUN_TEST(test_parse_simple_types);
  RUN_TEST(test_parse_limits_partial);
  RUN_TEST(test_parse_ping_ids);
  RUN_TEST(test_unknown_and_garbage_are_ignored);
  RUN_TEST(test_format_odom_imu);
  RUN_TEST(test_format_state);
  RUN_TEST(test_format_event_hello_pong_cal);
  RUN_TEST(test_line_buffer);
  return UNITY_END();
}
