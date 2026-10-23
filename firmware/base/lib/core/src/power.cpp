#include "power.h"

#include <math.h>

#include "config.h"

namespace power {

// Per-cell OCV table (V, %). 3S pack -> multiply by 3.
static const float kCellV[] = {3.00f, 3.30f, 3.40f, 3.50f, 3.60f, 3.70f,
                               3.80f, 3.90f, 4.00f, 4.10f, 4.20f};
static const float kPct[] = {0, 4, 8, 15, 25, 40, 55, 68, 80, 90, 100};
static const int kN = sizeof(kCellV) / sizeof(kCellV[0]);

int batteryPct(float pack_v) {
  if (!(pack_v == pack_v)) return 0;
  const float v = pack_v / 3.0f;
  if (v <= kCellV[0]) return 0;
  if (v >= kCellV[kN - 1]) return 100;
  for (int i = 1; i < kN; i++) {
    if (v <= kCellV[i]) {
      const float t = (v - kCellV[i - 1]) / (kCellV[i] - kCellV[i - 1]);
      return (int)lroundf(kPct[i - 1] + t * (kPct[i] - kPct[i - 1]));
    }
  }
  return 100;
}

float ntcResistance(float pin_mv, float vref_mv, float r_fixed) {
  const float rail = 0.015f * vref_mv;  // within ~50 mV of a rail = fault
  if (pin_mv < rail || pin_mv > vref_mv - rail) return -1;
  return r_fixed * pin_mv / (vref_mv - pin_mv);
}

float ntcCelsius(float r_ohm, float r25, float beta) {
  if (r_ohm <= 0) return NAN;
  const float inv = 1.0f / 298.15f + logf(r_ohm / r25) / beta;
  return 1.0f / inv - 273.15f;
}

Config defaultConfig() {
  Config c;
  c.bat_ratio = BAT_DIVIDER_RATIO;
  c.chg_ratio = CHG_DIVIDER_RATIO;
  c.vref_mv = ADC_VREF_MV;
  c.ntc_r_fixed = NTC_R_FIXED;
  c.ntc_r25 = NTC_R25;
  c.ntc_beta = NTC_BETA;
  c.dock_min_v = DOCK_MIN_V;
  c.dock_debounce_ms = DOCK_DEBOUNCE_MS;
  c.charge_delta_v = CHARGE_DELTA_V;
  c.bat_alpha = BAT_FILTER_ALPHA;
  c.low_pct = LOW_BATTERY_PCT;
  c.low_clear_pct = LOW_BATTERY_CLEAR_PCT;
  return c;
}

void Monitor::update(uint32_t now_ms, float bat_pin_mv, float ntc_pin_mv, float chg_pin_mv,
                     EventQueue& ev) {
  const float bat_v = bat_pin_mv * c_.bat_ratio / 1000.0f;
  chg_v_ = chg_pin_mv * c_.chg_ratio / 1000.0f;
  // Fast drops (BMS cut-off) must not be hidden by the filter: follow any
  // reading below the cut-off straight away.
  if (!seeded_ || bat_v < BMS_CUTOFF_V) bat_v_ = bat_v;
  else bat_v_ += c_.bat_alpha * (bat_v - bat_v_);

  const float r = ntcResistance(ntc_pin_mv, c_.vref_mv, c_.ntc_r_fixed);
  const float t = ntcCelsius(r, c_.ntc_r25, c_.ntc_beta);
  ntc_ok_ = r > 0 && t == t && t > -30.0f && t < 120.0f;
  if (ntc_ok_) pack_c_ = t;

  // Dock: debounced contact voltage.
  const bool raw = chg_v_ > c_.dock_min_v;
  if (!seeded_) {
    dock_raw_ = on_dock_ = raw;
    dock_change_ms_ = now_ms;
  } else {
    if (raw != dock_raw_) {
      dock_raw_ = raw;
      dock_change_ms_ = now_ms;
    }
    if (dock_raw_ != on_dock_ && (uint32_t)(now_ms - dock_change_ms_) >= c_.dock_debounce_ms) {
      on_dock_ = dock_raw_;
      ev.push(on_dock_ ? "dock_on" : "dock_off");
    }
  }
  // Charging = on the dock and the contacts sit above the pack (current flows
  // through the diode). Heuristic: no current sensor on the charge path.
  charging_ = on_dock_ && (chg_v_ - bat_v) > c_.charge_delta_v;

  pct_ = batteryPct(bat_v_);
  if (!low_ && pct_ < c_.low_pct && !charging_) {
    low_ = true;
    ev.push("low_battery");
  } else if (low_ && pct_ >= c_.low_clear_pct) {
    low_ = false;
  }
  seeded_ = true;
}

}  // namespace power
