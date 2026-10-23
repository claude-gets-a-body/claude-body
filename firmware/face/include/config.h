#pragma once
// =============================================================================
//  FACE firmware -- tunable constants. Hardware-free (native tests use it too).
// =============================================================================

#define FW_VERSION "face 0.1.0"
#define PI_BAUD 921600
#define PI_LINE_MAX 256

// ---- Displays ----------------------------------------------------------------
#define LCD_SPI_HZ 80000000      // 2 x 115 kB per frame: needs 80 MHz for >= 30 fps
#define LCD_ROTATION 0           // 0..3, both panels
#define LCD_INVERT 1             // most GC9A01 modules need colour inversion
#define EYE_SIZE 240
#define BL_PWM_HZ 20000
#define BL_PWM_BITS 10
#define BRIGHT_DEFAULT 0.8f
#define FRAME_MIN_MS 16          // cap ~60 fps

// ---- Eye look ------------------------------------------------------------------
#define EYE_COLOUR 0xD97757      // Claude orange
#define EYE_RIM_COLOUR 0xB45A40  // darker rim gives the iris an edge
#define EYE_HIGHLIGHT 0xFFF3EA   // warm white
#define GAZE_MAX_X_PX 34         // pupil travel at gaze +-1
#define GAZE_MAX_Y_PX 28
#define GAZE_TAU_MS 45           // saccade smoothing (fast but not instant)
#define MOOD_DEFAULT_MS 300

// ---- Blinks ----------------------------------------------------------------------
#define BLINK_MIN_MS 2000
#define BLINK_MAX_MS 6000
#define BLINK_DOUBLE_PCT 15      // chance a blink is a double blink
#define BLINK_CLOSE_MS 70
#define BLINK_HOLD_MS 40
#define BLINK_OPEN_MS 130
#define BLINK_DOUBLE_GAP_MS 120

// ---- Asleep breathing --------------------------------------------------------------
#define BREATH_PERIOD_MS 5000
#define BREATH_MIN 0.15f         // fraction of the set brightness
#define BREATH_MAX 0.45f

// ---- Visor -----------------------------------------------------------------------
#define VISOR_CLOSED_US 1000     // servo pulse with the visor DOWN over the lens
#define VISOR_OPEN_US 1900       // servo pulse with the visor UP
#define VISOR_MOVE_MS 400        // pulse ramp (gentle motion)
#define VISOR_OPEN_TIMEOUT_MS 1500  // switch must close within this, else `jammed`
#define VISOR_CLOSE_MS 700       // assume closed this long after commanding close
#define VISOR_SW_DEBOUNCE_MS 30

// ---- Ears ------------------------------------------------------------------------
#define EAR_L_DOWN_US 1900       // pulse at pose 0 (down) / 1 (up), per ear
#define EAR_L_UP_US 1100         // (the right ear is mounted mirrored)
#define EAR_R_DOWN_US 1100
#define EAR_R_UP_US 1900
#define EAR_SLEW_PER_S 2.5f      // pose units per second
#define EAR_WIGGLE_MS 1200
#define EAR_WIGGLE_HZ 5.0f
#define EAR_WIGGLE_AMP 0.12f

// ---- Servo PWM -------------------------------------------------------------------
#define SERVO_PWM_HZ 50
#define SERVO_PWM_BITS 14

// ---- Head range sensor (VL53L1X) ---------------------------------------------
#define RANGE_REPORT_MS 100      // `range` at 10 Hz
#define RANGE_TIMING_BUDGET_US 50000  // long mode, 50 ms budget
#define RANGE_PERIOD_MS 66       // continuous measurement period (~15 Hz)
#define RANGE_STALE_MS 300       // no fresh reading this long -> -1
#define RANGE_RETRY_MS 30000     // re-init a dead sensor this often (blocks ~60 ms,
                                 // a one-frame hitch in the eyes, so not too often)
#define RANGE_CLEAR_MM 4000      // "nothing in range"

// ---- Touch (TTP223) ---------------------------------------------------------------
#define TOUCH_ACTIVE_HIGH 1
#define TOUCH_DEBOUNCE_MS 20
#define TOUCH_HOLD_MS 1500       // > 1.5 s = hold
#define TOUCH_DOUBLE_GAP_MS 350  // second tap within this = double
