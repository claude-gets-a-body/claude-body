#pragma once
// =============================================================================
//  BASE firmware -- tunable constants. Hardware-free: the native unit tests
//  include this file too, so the tests check the real compiled-in numbers.
// =============================================================================

#ifdef BENCH_BUILD
#define FW_VERSION "base 0.1.0 bench"
#else
#define FW_VERSION "base 0.1.0"
#endif

// ---- Serial link to the Pi -------------------------------------------------
#define PI_BAUD 921600          // USB CDC ignores baud, kept for tooling
#define PI_LINE_MAX 384           // longest accepted input line (bytes)

// ---- Geometry (DESIGN.md 3.1) ------------------------------------------------
#define WHEEL_DIAMETER_M 0.100f
#define TRACK_WIDTH_M 0.172f         // wheel centres at +-86 mm
#define STS_STEPS_PER_REV 4096

// ---- Compiled-in motion caps (PROTOCOL 1, "Reflexes") ------------------------
#define CAP_V_MAX 0.25f         // m/s
#define CAP_W_MAX 1.5f          // rad/s
#define CAP_A_MAX 0.5f          // m/s^2, applied per wheel (also the watchdog ramp-down)
// Emergency braking (bump, drop, tilt, obstacle < 60 mm, pack hot, `stop`):
// from 0.25 m/s that is ~21 mm of travel, inside the 89 mm the front drop
// sensors sit ahead of the wheels. Never used to speed up.
#define A_ESTOP 1.5f            // m/s^2
#define CAP_WHEEL_V_MAX 0.25f   // m/s at the tyre; v + w*track/2 is scaled to fit

// ---- Reflex thresholds ---------------------------------------------------------
#define WATCHDOG_MS 300
#define STOP_BRAKE_MS 200          // `stop`: brake at zero speed, then coast (torque off)
#define BUMP_HOLDOFF_MS 1000
#define REFLEX_REVERSE_MAX 0.08f   // m/s allowed AWAY from a hazard: backwards after a
                                   // bump/front drop, forwards after a rear drop
#define REFLEX_W_MAX 0.5f          // rad/s turn allowed while bump/drop is active
                                   // (not in PROTOCOL; lets the Pi rotate away)
#define DROP_MARGIN_MM 60          // drop if reading > floor + this
#define DROP_CLEAR_MS 100          // all down sensors good this long -> clear
#define TOF_STALE_MS 150           // no fresh reading this long -> treat as drop/fault
// Obstacle distances are measured from the BUMPER FACE. The forward ToFs sit
// FWD_TOF_OFFSET_MM behind it, so 60 mm here = 105 mm at the sensor (safely
// above the VL53L1X's 40 mm minimum accurate range).
#define FWD_TOF_OFFSET_MM 45
#define OBSTACLE_SLOW_MM 120
#define OBSTACLE_STOP_MM 60
#define OBSTACLE_HYST_MM 15
#define OBSTACLE_SLOW_V 0.05f
// The static tip angle over the wheel-to-rear-ball diagonal is ~19-21 deg, so
// 15 deg stays below it.
#define TILT_LIMIT_DEG 15.0f
#define TILT_UPRIGHT_DEG 10.0f     // must be below this ...
#define TILT_UPRIGHT_MS 2000       // ... for this long before `torque on` is accepted
#define TILT_BRAKE_MAX_MS 300      // tilt: brake at A_ESTOP, then torque off (at the
                                   // latest this long after the tilt)
#define PACK_HOT_C 50.0f
#define PACK_COOL_C 45.0f          // hysteresis: pack_hot clears below this
#define NTC_FAULT_BLOCKS_MOTION 1  // open/shorted NTC = treated as pack_hot
#define BMS_CUTOFF_V 6.0f          // pack reads below this = BMS has cut off
#define LOW_BATTERY_PCT 15
#define LOW_BATTERY_CLEAR_PCT 20

// ---- Floor calibration (drop sensors) -------------------------------------------
#define CAL_SAMPLES 15             // valid readings per sensor
#define CAL_TIMEOUT_MS 2000
// Down sensors sit ~50 mm above the floor (VL53L1X is accurate from 40 mm).
// A calibrated floor outside CAL_MIN..CAL_MAX, or one that disagrees with the
// other down sensors by more than CAL_AGREE_MM, is rejected (robot held in the
// air, or a sensor over a step edge). The bench build (env base_bench) widens
// the window so calibration works with the robot on a stand.
#define CAL_MIN_MM 35
#ifndef CAL_MAX_MM
#define CAL_MAX_MM 90
#endif
#define CAL_AGREE_MM 15
#define FLOOR_DEFAULT_MM 50        // used until a calibration succeeds

// ---- Battery / power -----------------------------------------------------------
#define BAT_DIVIDER_RATIO ((100.0f + 22.0f) / 22.0f)
#define CHG_DIVIDER_RATIO ((100.0f + 22.0f) / 22.0f)
#define ADC_VREF_MV 3300.0f        // supply of the NTC divider
#define NTC_R_FIXED 10000.0f
#define NTC_R25 10000.0f
#define NTC_BETA 3950.0f
#define DOCK_MIN_V 9.0f            // contacts above this = on dock
#define DOCK_DEBOUNCE_MS 500
#define CHARGE_DELTA_V 0.15f       // contacts this far above pack = current flowing
#define BAT_FILTER_ALPHA 0.05f     // EMA per 5 Hz sample (~4 s time constant)

// ---- Feetech bus -------------------------------------------------------------
#define STS_BAUD 1000000
#define STS_BYTE_TIMEOUT_US 1500   // inter-byte timeout for replies (time-box)
// Does the half-duplex adapter echo our own TX bytes back on RX?
//   0 = no echo, 1 = echo, 2 = auto-detect at servo init (ping an unused ID)
#define STS_BUS_ECHO 2
#define STS_FAIL_LIMIT 3           // consecutive failed reads -> servo_error
#define SERVO_ID_LEFT 1
#define SERVO_ID_RIGHT 2
#define SERVO_ID_PAN 3
#define SERVO_ID_TILT 4
#define RIGHT_WHEEL_SIGN (-1)      // right wheel is mounted mirrored
#define LEFT_WHEEL_SIGN (+1)
#define STS_MAX_SPEED_STEPS 3400   // goal-speed clamp (steps/s); reg 46 max per Feetech table
// Reg 14 "max input voltage" (0.1 V). The 7.4 V table default is 80 (8.0 V); a
// servo set that low will fault on the 3S pack. Checked at init -> servo_error.
#define STS_MIN_VMAX_SETTING 130   // need >= 13.0 V for a 12.6 V pack
// Torque limit, SRAM reg 48, 0..1000 = 0..100 %. DESIGN.md says ~30 % for the
// wheels. For the FIRST power-on use 100 (10 %), see README bring-up.
#define WHEEL_TORQUE_LIMIT 300     // 30 %: hard ceiling, see servo_cfg.cpp (<= 300)
#define HEAD_TORQUE_LIMIT 100      // 10 %: the neck must never push hard enough to
                                   // hurt a child's face (hard ceiling <= 100)
// Overload / protection settings (EEPROM; register names from the ST3215
// memory table V3.7, regs.csv). Written at bring-up only if different, then
// read back; a servo that doesn't verify never gets torque.
//   reg 28 protection current      6.5 mA units
//   reg 34 protection torque       %   output after overload protection trips
//   reg 35 protection time         10 ms  overload must last this long
//   reg 36 overload torque         %   threshold that starts the countdown
//   reg 38 overcurrent prot. time  10 ms
//   reg 19 unloading conditions    bits 3 (current) and 5 (overload) forced on
// NOTE: whether the % values are of stall torque or of reg 16 is not stated
// in the table; these values are protective under either reading.
#define WHEEL_PROT_CURRENT 150     // 975 mA (stall is ~2.7 A)
#define WHEEL_OVERLOAD_TORQUE 25   // %
#define WHEEL_PROT_TIME 100        // 1.0 s
#define WHEEL_PROT_TORQUE 10       // %
#define HEAD_PROT_CURRENT 60       // 390 mA
#define HEAD_OVERLOAD_TORQUE 8     // %
#define HEAD_PROT_TIME 50          // 0.5 s
#define HEAD_PROT_TORQUE 5         // %
#define WHEEL_ACC 0                // reg 41 in wheel mode; 0 = firmware ramp only
#define HEAD_ACC 40                // reg 41, units of 100 steps/s^2
#define BOOT_TORQUE_ON 1           // 1 = hold position at boot, 0 = boot limp
#define TORQUE_VERIFY_MS 200       // read reg 40 back this often and repair mismatches

// ---- Head (PROTOCOL 1 `head`) ---------------------------------------------------
#define PAN_MIN_DEG -150.0f
#define PAN_MAX_DEG 150.0f
#define TILT_MIN_DEG -15.0f        // hard mechanical stops at -16 / +31 deg; the
#define TILT_MAX_DEG 30.0f         // servo's EEPROM angle limits are set to these too
#define HEAD_SPEED_MAX_DPS 120.0f
#define HEAD_SPEED_DEFAULT_DPS 60.0f
#define PAN_CENTER_STEPS 2048      // servo step at 0 deg (after mid-point calibration)
#define TILT_CENTER_STEPS 2048
#define PAN_DIR (+1)               // +1: increasing steps = +deg (left). Flip if mounted the other way.
#define TILT_DIR (+1)              // +1: increasing steps = up

// ---- IMU ----------------------------------------------------------------------
// Default: BNO085 (on-chip fusion, Adafruit BNO08x lib, I2C 0x4A).
// Build with -DIMU_MPU6050 (env base_mpu6050) to use an MPU-6050 instead.
#define BNO085_I2C_ADDR 0x4A
#define BNO085_REPORT_US 10000    // 100 Hz game rotation vector + gyro
#define IMU_STALE_MS 200           // no fresh sample this long -> imu not ok (tilt latch)
// Mounting rotation: robot axes (x forward, y left, z up) = IMU_R * sensor axes.
#define IMU_R {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}}
#define IMU_COMP_ALPHA 0.98f       // complementary filter gyro weight
#define IMU_BIAS_SAMPLES 200       // gyro bias averaged at boot (robot still)
#define IMU_PERIOD_MS 10

// ---- Motor power sense (analogue: the servo rail after the kill rocker) --------
#define MOTOR_DIVIDER_RATIO ((100.0f + 33.0f) / 33.0f)
#define MOTOR_ON_V 7.0f            // rail above this = motors powered
#define MOTOR_OFF_V 6.0f           // ... below this = off (hysteresis)
#define MOTOR_SENSE_DEBOUNCE_MS 60

// ---- Rates -------------------------------------------------------------------
#define CONTROL_PERIOD_MS 20       // 50 Hz: drive, odom, imu reports
#define STATE_PERIOD_MS 200        // 5 Hz: state report, head/ADC reads
#define LED_PERIOD_MS 20
#define BUMP_SAMPLE_US 1000
#define BUMP_PRESS_MS 3            // debounce: stable this long to count as pressed
#define BUMP_RELEASE_MS 20         // ... and as released

// ---- Chest ring -------------------------------------------------------------------
#define LED_COUNT 16                // 16-LED WS2812 chest ring
#define LED_MAX_BRIGHTNESS 120     // 0..255 global cap (current + glare)
#define LED_DEFAULT_RGB {0xD9, 0x77, 0x57}  // Claude orange
