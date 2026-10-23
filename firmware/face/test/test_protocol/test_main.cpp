#include <ArduinoJson.h>
#include <string.h>
#include <unity.h>

#include "line_buffer.h"
#include "protocol.h"

using namespace face;

void setUp() {}
void tearDown() {}

void test_mood() {
  Command c;
  TEST_ASSERT_EQUAL(Type::Mood, parse("{\"t\":\"mood\",\"m\":\"happy\",\"ms\":500}", c));
  TEST_ASSERT_EQUAL(HAPPY, c.mood);
  TEST_ASSERT_TRUE(c.has_ms);
  TEST_ASSERT_EQUAL_UINT32(500, c.ms);
  TEST_ASSERT_EQUAL(Type::Mood, parse("{\"t\":\"mood\",\"m\":\"asleep\"}", c));
  TEST_ASSERT_FALSE(c.has_ms);
  TEST_ASSERT_EQUAL(Type::Mood, parse("{\"t\":\"mood\",\"m\":\"sad\",\"ms\":-50}", c));
  TEST_ASSERT_EQUAL_UINT32(0, c.ms);  // clamped
  TEST_ASSERT_EQUAL(Type::Invalid, parse("{\"t\":\"mood\",\"m\":\"furious\"}", c));
  TEST_ASSERT_EQUAL(Type::Invalid, parse("{\"t\":\"mood\"}", c));
}

void test_gaze_clamped() {
  Command c;
  TEST_ASSERT_EQUAL(Type::Gaze, parse("{\"t\":\"gaze\",\"x\":-0.5,\"y\":3}", c));
  TEST_ASSERT_FLOAT_WITHIN(1e-6, -0.5f, c.x);
  TEST_ASSERT_EQUAL_FLOAT(1.0f, c.y);
  TEST_ASSERT_EQUAL(Type::Invalid, parse("{\"t\":\"gaze\",\"x\":0}", c));
}

void test_ears() {
  Command c;
  TEST_ASSERT_EQUAL(Type::Ears, parse("{\"t\":\"ears\",\"l\":0.2,\"r\":1.4}", c));
  TEST_ASSERT_TRUE(c.has_l && c.has_r);
  TEST_ASSERT_FLOAT_WITHIN(1e-6, 0.2f, c.l);
  TEST_ASSERT_EQUAL_FLOAT(1.0f, c.r);
  TEST_ASSERT_FALSE(c.wiggle);
  TEST_ASSERT_EQUAL(Type::Ears, parse("{\"t\":\"ears\",\"wiggle\":true}", c));
  TEST_ASSERT_TRUE(c.wiggle);
  TEST_ASSERT_FALSE(c.has_l);
  TEST_ASSERT_EQUAL(Type::Invalid, parse("{\"t\":\"ears\",\"wiggle\":false}", c));
}

void test_visor_bright_blink() {
  Command c;
  TEST_ASSERT_EQUAL(Type::Visor, parse("{\"t\":\"visor\",\"open\":true}", c));
  TEST_ASSERT_TRUE(c.open);
  TEST_ASSERT_EQUAL(Type::Invalid, parse("{\"t\":\"visor\",\"open\":\"yes\"}", c));
  TEST_ASSERT_EQUAL(Type::Bright, parse("{\"t\":\"bright\",\"b\":1.7}", c));
  TEST_ASSERT_EQUAL_FLOAT(1.0f, c.b);
  TEST_ASSERT_EQUAL(Type::Blink, parse("{\"t\":\"blink\"}", c));
  TEST_ASSERT_EQUAL(Type::Ping, parse("{\"t\":\"ping\",\"id\":3}", c));
  TEST_ASSERT_EQUAL_STRING("3", c.id_json);
}

void test_unknown_and_garbage() {
  Command c;
  TEST_ASSERT_EQUAL(Type::Unknown, parse("{\"t\":\"sing\"}", c));
  TEST_ASSERT_EQUAL(Type::Invalid, parse("}{", c));
  TEST_ASSERT_EQUAL(Type::Invalid, parse("{\"m\":\"happy\"}", c));
}

static void valid(const char* b, size_t n, const char* t) {
  TEST_ASSERT_TRUE(n > 0);
  TEST_ASSERT_EQUAL_CHAR('\n', b[n - 1]);
  JsonDocument d;
  TEST_ASSERT_EQUAL(DeserializationError::Ok, deserializeJson(d, b).code());
  TEST_ASSERT_EQUAL_STRING(t, d["t"]);
}

void test_formatters() {
  char b[96];
  valid(b, fmtVisor(b, sizeof b, "jammed"), "visor");
  TEST_ASSERT_NOT_NULL(strstr(b, "\"state\":\"jammed\""));
  valid(b, fmtTouch(b, sizeof b, "double"), "touch");
  TEST_ASSERT_NOT_NULL(strstr(b, "\"g\":\"double\""));
  valid(b, fmtHello(b, sizeof b, "face 0.1.0"), "hello");
  valid(b, fmtPong(b, sizeof b, "\"abc\""), "pong");
  TEST_ASSERT_EQUAL(0u, fmtHello(b, 8, "face 0.1.0"));
}

void test_range_message_and_values() {
  char b[64];
  valid(b, fmtRange(b, sizeof b, 731), "range");
  JsonDocument d;
  deserializeJson(d, b);
  TEST_ASSERT_EQUAL(731, d["head_mm"].as<int>());
  valid(b, fmtRange(b, sizeof b, -1), "range");
  TEST_ASSERT_NOT_NULL(strstr(b, "\"head_mm\":-1"));
  // classification
  TEST_ASSERT_EQUAL(-1, headRangeValue(false, true, 0, 500));    // dead sensor
  TEST_ASSERT_EQUAL(-1, headRangeValue(true, false, 0, 500));    // stale
  TEST_ASSERT_EQUAL(500, headRangeValue(true, true, 0, 500));    // valid
  TEST_ASSERT_EQUAL(480, headRangeValue(true, true, 1, 480));    // sigma fail: still a target
  TEST_ASSERT_EQUAL(4000, headRangeValue(true, true, 2, 0));     // nothing seen = clear
  TEST_ASSERT_EQUAL(4000, headRangeValue(true, true, 4, 0));
  TEST_ASSERT_EQUAL(0, headRangeValue(true, true, 13, 0));       // too close to measure
  TEST_ASSERT_EQUAL(-1, headRangeValue(true, true, 5, 300));     // hardware fail
  TEST_ASSERT_EQUAL(-1, headRangeValue(true, true, 255, 0));     // no reading yet
  TEST_ASSERT_EQUAL(4000, headRangeValue(true, true, 0, 5200));  // clamped
}

void test_line_buffer_drops_overlong() {
  LineBuffer<8> lb;
  const char* in = "0123456789\n{}\n";
  int n = 0;
  for (const char* p = in; *p; p++)
    if (lb.push(*p)) {
      n++;
      TEST_ASSERT_EQUAL_STRING("{}", lb.line());
    }
  TEST_ASSERT_EQUAL(1, n);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_mood);
  RUN_TEST(test_gaze_clamped);
  RUN_TEST(test_ears);
  RUN_TEST(test_visor_bright_blink);
  RUN_TEST(test_unknown_and_garbage);
  RUN_TEST(test_formatters);
  RUN_TEST(test_range_message_and_values);
  RUN_TEST(test_line_buffer_drops_overlong);
  return UNITY_END();
}
