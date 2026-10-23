#pragma once
// ToF interpretation: floor calibration (median), drop detection, forward
// obstacle values. Hardware-free.
#include <stdint.h>

namespace tof {

// Forward sensor value meaning "no target in range" (range status says signal
// fail / out of bounds: nothing is there). Reported in `fwd_mm` as-is.
static const int kNoTarget = 4000;
// Forward sensor value meaning "no usable reading" (sensor dead/stale/hardware
// fault). Reported in `fwd_mm` as -1 and treated as a near obstacle (slow).
static const int kFault = -1;

// VL53L1X range_status codes (Pololu VL53L1X::RangeStatus).
enum RangeStatus : uint8_t {
  RangeValid = 0,
  SigmaFail = 1,
  SignalFail = 2,
  RangeValidMinRangeClipped = 3,
  OutOfBoundsFail = 4,
  HardwareFail = 5,
  RangeValidNoWrapCheckFail = 6,
  WrapTargetFail = 7,
  XtalkSignalFail = 9,
  SynchronizationInt = 10,
  MinRangeFail = 13,
  None = 255,
};

// Down sensors: only a clean, fresh reading counts as "floor seen".
bool downReadingOk(uint8_t status, bool fresh);

// Forward sensors: mm if valid, kNoTarget if nothing seen, kFault otherwise.
int forwardValue(uint8_t status, int mm, bool fresh);

// Forward sensor value -> distance from the bumper face (the sensor sits
// offset_mm behind it). kNoTarget / kFault pass through; never negative.
int bumperDistance(int fwd_value, int offset_mm);

// Collects samples for one sensor and returns the median.
class MedianCal {
 public:
  static const int kMaxSamples = 31;
  void reset() { n_ = 0; }
  void add(int mm) {
    if (n_ < kMaxSamples) s_[n_++] = mm;
  }
  int count() const { return n_; }
  // Median of the samples collected so far (0 if none).
  int median() const;

 private:
  int s_[kMaxSamples];
  int n_ = 0;
};

// Floor calibration of all down sensors, driven by the main loop.
class FloorCal {
 public:
  static const int kSensors = 3;
  FloorCal(int samples, uint32_t timeout_ms, int min_mm, int max_mm, int default_mm,
           int agree_mm = 1000);
  void start(uint32_t now_ms);
  bool running() const { return running_; }
  // Feed a reading (only valid ones should be passed).
  void addSample(int sensor, int mm);
  // Returns true on the tick the calibration finishes (done or timed out).
  bool tick(uint32_t now_ms);
  int floorMm(int sensor) const { return floor_[sensor]; }
  bool lastOk(int sensor) const { return ok_[sensor]; }

 private:
  int samples_, min_mm_, max_mm_, agree_mm_;
  uint32_t timeout_ms_, start_ms_ = 0;
  bool running_ = false;
  MedianCal med_[kSensors];
  int floor_[kSensors];
  bool ok_[kSensors];
};

// Drop detector for one down sensor: set immediately on a bad reading,
// cleared only after clear_ms of continuously good readings.
class DropDetector {
 public:
  DropDetector(int margin_mm, uint32_t clear_ms) : margin_(margin_mm), clear_ms_(clear_ms) {}
  // ok: downReadingOk(); mm: distance; floor_mm: calibrated floor.
  // forced: e.g. calibration running -> counts as a drop.
  bool update(uint32_t now_ms, bool ok, int mm, int floor_mm, bool forced = false);
  bool drop() const { return drop_; }

 private:
  int margin_;
  uint32_t clear_ms_;
  bool drop_ = true;  // fail-safe until proven otherwise
  uint32_t last_bad_ms_ = 0;
  bool bad_seen_ = true;
};

}  // namespace tof
