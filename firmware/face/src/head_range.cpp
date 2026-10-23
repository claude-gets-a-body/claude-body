#include "head_range.h"

#include <VL53L1X.h>
#include <Wire.h>

#include "config.h"
#include "pins.h"
#include "protocol.h"

static VL53L1X tof;

bool HeadRange::init() {
  digitalWrite(PIN_HEAD_TOF_XSHUT, LOW);  // hard reset
  delay(2);
  digitalWrite(PIN_HEAD_TOF_XSHUT, HIGH);
  delay(3);
  tof.setBus(&Wire);
  tof.setTimeout(50);
  if (!tof.init()) return alive_ = false;
  tof.setDistanceMode(VL53L1X::Long);  // table edges can be a few metres away
  tof.setMeasurementTimingBudget(RANGE_TIMING_BUDGET_US);
  tof.startContinuous(RANGE_PERIOD_MS);
  status_ = 255;
  last_ms_ = millis();
  return alive_ = true;
}

bool HeadRange::begin() {
  pinMode(PIN_HEAD_TOF_XSHUT, OUTPUT);
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, 400000);
  Wire.setTimeOut(5);  // a stuck bus can't hang the eyes for long
  return init();
}

void HeadRange::poll(uint32_t now) {
  if (!alive_) {
    if ((uint32_t)(now - last_retry_ms_) >= RANGE_RETRY_MS) {
      last_retry_ms_ = now;
      init();
    }
    return;
  }
  if ((uint32_t)(now - last_check_ms_) < 10) return;
  last_check_ms_ = now;
  if (tof.dataReady()) {
    tof.read(false);
    mm_ = tof.ranging_data.range_mm;
    status_ = (uint8_t)tof.ranging_data.range_status;
    last_ms_ = now;
  } else if ((uint32_t)(now - last_ms_) > 1000) {
    alive_ = false;  // stopped answering: report -1, retry later
    last_retry_ms_ = now;
  }
}

int HeadRange::value(uint32_t now) const {
  const bool fresh = status_ != 255 && (uint32_t)(now - last_ms_) < RANGE_STALE_MS;
  return face::headRangeValue(alive_, fresh, status_, mm_);
}
