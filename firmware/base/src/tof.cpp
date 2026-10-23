#include "tof.h"

#include "pins.h"

static const uint8_t kXshut[TOF_COUNT] = {PIN_XSHUT_DOWN_L, PIN_XSHUT_DOWN_REAR, PIN_XSHUT_DOWN_R,
                                          PIN_XSHUT_FWD_L, PIN_XSHUT_FWD_R};
static const uint8_t kAddr[TOF_COUNT] = {0x30, 0x31, 0x32, 0x33, 0x34};

bool TofArray::initOne(int i) {
  digitalWrite(kXshut[i], HIGH);
  delay(3);  // boot time ~1.2 ms
  s_[i].setBus(wire_);
  s_[i].setAddress(0x29);  // the library's notion of the default address
  s_[i].setTimeout(50);
  if (!s_[i].init()) {
    digitalWrite(kXshut[i], LOW);
    r_[i].alive = false;
    return false;
  }
  s_[i].setAddress(kAddr[i]);
  s_[i].setDistanceMode(VL53L1X::Short);        // best ambient immunity, to ~1.3 m
  s_[i].setMeasurementTimingBudget(20000);      // 20 ms
  s_[i].startContinuous(25);                    // 40 Hz
  r_[i].alive = true;
  r_[i].status = 255;
  return true;
}

int TofArray::begin(TwoWire& wire) {
  wire_ = &wire;
  for (int i = 0; i < TOF_COUNT; i++) {
    pinMode(kXshut[i], OUTPUT);
    digitalWrite(kXshut[i], LOW);
  }
  delay(5);
  int n = 0;
  for (int i = 0; i < TOF_COUNT; i++) n += initOne(i) ? 1 : 0;
  return n;
}

void TofArray::retryDead(uint32_t now) {
  if ((uint32_t)(now - last_retry_ms_) < 5000) return;
  last_retry_ms_ = now;
  for (int i = 0; i < TOF_COUNT; i++) {
    if (r_[i].alive) continue;
    digitalWrite(kXshut[i], LOW);
    delay(2);
    initOne(i);
    return;  // at most one per retry period
  }
}

int TofArray::poll(uint32_t now) {
  for (int k = 0; k < TOF_COUNT; k++) {
    const int i = next_;
    next_ = (next_ + 1) % TOF_COUNT;
    if (!r_[i].alive || (uint32_t)(now - last_check_ms_[i]) < 4) continue;
    last_check_ms_[i] = now;
    if (!s_[i].dataReady()) {
      // A sensor that stops answering goes stale (handled by the reflexes);
      // mark it dead after 1 s so retryDead() can bring it back.
      if (r_[i].status != 255 && (uint32_t)(now - r_[i].last_ms) > 1000) r_[i].alive = false;
      return -1;
    }
    s_[i].read(false);
    r_[i].mm = s_[i].ranging_data.range_mm;
    r_[i].status = (uint8_t)s_[i].ranging_data.range_status;
    r_[i].last_ms = now;
    return i;
  }
  return -1;
}

uint8_t TofArray::aliveMask() const {
  uint8_t m = 0;
  for (int i = 0; i < TOF_COUNT; i++)
    if (r_[i].alive) m |= 1 << i;
  return m;
}
