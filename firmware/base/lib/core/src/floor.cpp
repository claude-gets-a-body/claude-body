#include "floor.h"

namespace tof {

bool downReadingOk(uint8_t status, bool fresh) { return fresh && status == RangeValid; }

int forwardValue(uint8_t status, int mm, bool fresh) {
  if (!fresh) return kFault;
  switch (status) {
    case RangeValid:
    case SigmaFail:  // noisy but still a target estimate: err towards caution
      return mm < 0 ? 0 : mm;
    case SignalFail:
    case OutOfBoundsFail:
    case WrapTargetFail:
    case XtalkSignalFail:
      return kNoTarget;  // nothing (reliable) in front
    case RangeValidMinRangeClipped:
    case MinRangeFail:
      return 0;  // something very close
    default:
      return kFault;
  }
}

int bumperDistance(int v, int offset_mm) {
  if (v == kNoTarget || v == kFault) return v;
  v -= offset_mm;
  return v < 0 ? 0 : v;
}

int MedianCal::median() const {
  if (n_ == 0) return 0;
  int t[kMaxSamples];
  for (int i = 0; i < n_; i++) t[i] = s_[i];
  for (int i = 1; i < n_; i++) {  // insertion sort, n <= 31
    int v = t[i], j = i - 1;
    while (j >= 0 && t[j] > v) {
      t[j + 1] = t[j];
      j--;
    }
    t[j + 1] = v;
  }
  if (n_ & 1) return t[n_ / 2];
  return (t[n_ / 2 - 1] + t[n_ / 2]) / 2;
}

FloorCal::FloorCal(int samples, uint32_t timeout_ms, int min_mm, int max_mm, int default_mm,
                   int agree_mm)
    : samples_(samples > MedianCal::kMaxSamples ? MedianCal::kMaxSamples : samples),
      min_mm_(min_mm),
      max_mm_(max_mm),
      agree_mm_(agree_mm),
      timeout_ms_(timeout_ms) {
  for (int i = 0; i < kSensors; i++) {
    floor_[i] = default_mm;
    ok_[i] = false;
  }
}

void FloorCal::start(uint32_t now_ms) {
  running_ = true;
  start_ms_ = now_ms;
  for (int i = 0; i < kSensors; i++) med_[i].reset();
}

void FloorCal::addSample(int sensor, int mm) {
  if (!running_ || sensor < 0 || sensor >= kSensors) return;
  med_[sensor].add(mm);
}

bool FloorCal::tick(uint32_t now_ms) {
  if (!running_) return false;
  bool all = true;
  for (int i = 0; i < kSensors; i++)
    if (med_[i].count() < samples_) all = false;
  if (!all && (uint32_t)(now_ms - start_ms_) < timeout_ms_) return false;
  // 1) each sensor: enough samples and a plausible distance
  int m[kSensors];
  int good[kSensors], ng = 0;
  for (int i = 0; i < kSensors; i++) {
    m[i] = med_[i].median();
    ok_[i] = med_[i].count() >= (samples_ + 1) / 2 && m[i] >= min_mm_ && m[i] <= max_mm_;
    if (ok_[i]) good[ng++] = m[i];
  }
  // 2) the sensors must agree with each other (a step edge under one of them
  //    reads far but may still be inside the window)
  if (ng >= 2) {
    for (int a = 1; a < ng; a++)  // sort the few good values
      for (int b = a; b > 0 && good[b - 1] > good[b]; b--) {
        const int t = good[b];
        good[b] = good[b - 1];
        good[b - 1] = t;
      }
    const int ref = (ng & 1) ? good[ng / 2] : (good[ng / 2 - 1] + good[ng / 2]) / 2;
    for (int i = 0; i < kSensors; i++)
      if (ok_[i] && (m[i] - ref > agree_mm_ || ref - m[i] > agree_mm_)) ok_[i] = false;
  }
  // 3) accepted values replace the floor; rejected ones keep the previous value
  for (int i = 0; i < kSensors; i++)
    if (ok_[i]) floor_[i] = m[i];
  running_ = false;
  return true;
}

bool DropDetector::update(uint32_t now_ms, bool ok, int mm, int floor_mm, bool forced) {
  const bool bad = forced || !ok || mm > floor_mm + margin_;
  if (bad) {
    drop_ = true;
    last_bad_ms_ = now_ms;
    bad_seen_ = true;
  } else if (drop_) {
    if (bad_seen_) {
      // first good reading after a bad one starts the clear timer
      bad_seen_ = false;
      last_bad_ms_ = now_ms;
    }
    if ((uint32_t)(now_ms - last_bad_ms_) >= clear_ms_) drop_ = false;
  }
  return drop_;
}

}  // namespace tof
