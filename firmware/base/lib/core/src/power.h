#pragma once
// Battery, pack temperature and dock-contact interpretation. Hardware-free.
#include <stdint.h>

#include "events.h"

namespace power {

// 3S Li-ion resting voltage -> state of charge, 0..100 (piecewise linear on a
// typical 18650 discharge curve; 9.0 V = 0 %, 12.6 V = 100 %).
int batteryPct(float pack_v);

// NTC to GND, fixed resistor to vref: resistance from the pin voltage.
// Returns < 0 if the reading is at a rail (open or shorted NTC).
float ntcResistance(float pin_mv, float vref_mv, float r_fixed);
// Beta equation. r <= 0 -> NAN.
float ntcCelsius(float r_ohm, float r25, float beta);

struct Config {
  float bat_ratio, chg_ratio;   // divider ratios (V_in / V_pin)
  float vref_mv, ntc_r_fixed, ntc_r25, ntc_beta;
  float dock_min_v;
  uint32_t dock_debounce_ms;
  float charge_delta_v;
  float bat_alpha;              // EMA weight per sample
  int low_pct, low_clear_pct;
};
Config defaultConfig();  // from config.h

class Monitor {
 public:
  explicit Monitor(const Config& c) : c_(c) {}
  // Raw pin millivolts. Call at a steady rate (5 Hz).
  void update(uint32_t now_ms, float bat_pin_mv, float ntc_pin_mv, float chg_pin_mv,
              EventQueue& ev);
  float batV() const { return bat_v_; }
  int pct() const { return pct_; }
  bool ntcOk() const { return ntc_ok_; }
  float packC() const { return pack_c_; }
  bool onDock() const { return on_dock_; }
  bool charging() const { return charging_; }
  float contactV() const { return chg_v_; }
  bool seeded() const { return seeded_; }

 private:
  Config c_;
  bool seeded_ = false;
  float bat_v_ = 0, chg_v_ = 0, pack_c_ = 25;
  int pct_ = 0;
  bool ntc_ok_ = false;
  bool on_dock_ = false, charging_ = false;
  bool dock_raw_ = false;
  uint32_t dock_change_ms_ = 0;
  bool low_ = false;
};

}  // namespace power
