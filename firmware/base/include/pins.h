#pragma once
// =============================================================================
//  BASE ESP32-S3 ("spine") -- every GPIO in one place.
//  Board: ESP32-S3-DevKitC-1 N8R2. Change pins here only.
//
//  Pins to AVOID on this board:
//    GPIO0, 3, 45, 46     strapping pins
//    GPIO19, 20           native USB D-/D+ (this is our serial link to the Pi)
//    GPIO26..32           SPI flash / PSRAM
//    GPIO33..37           reserved for octal PSRAM on other modules (left free)
//    GPIO38 / GPIO48      on-board RGB LED (v1.1 / v1.0 boards)
//    GPIO43, 44           UART0, wired to the board's USB-UART "UART" port
//  ADC: only ADC1 (GPIO1..10) is used, so Wi-Fi can never disturb a reading.
//
//  WIRING
//  ------------------------------------------------------------------------
//  Feetech bus via Waveshare Bus Servo Adapter (A), jumper on "A" (UART mode).
//  Its UART header is TX / RX / GND; the adapter handles half-duplex direction.
//    GPIO17 (ESP TX) -> adapter RX
//    GPIO18 (ESP RX) <- adapter TX
//    GND             -- adapter GND (common ground with the servo supply!)
//    If a first ping finds no servos, swap TX/RX before anything else: the
//    label convention on the header has not been checked on the real board.
//  Servo power: 3S pack -> motor kill rocker -> adapter power input (straight
//  through to the servos). Use the 12 V STS3215 (C018/C047, 1:345 gear).
//    Servos: ID1 left wheel, ID2 right wheel (mirrored), ID3 neck pan, ID4 head tilt
//
//  I2C bus (3.3 V, 400 kHz, 2.2k pull-ups once for the whole bus):
//    GPIO8   SDA    -> 5 x VL53L1X + IMU (BNO085 at 0x4A, or MPU-6050 at 0x68)
//    GPIO9   SCL
//    VL53L1X XSHUT lines (each module held in reset until given its address):
//    GPIO10  XSHUT down-left     (I2C addr 0x30)  front-left, +27 deg, r 100 mm
//    GPIO11  XSHUT down-REAR     (0x31)  145 deg, r 95 mm (the robot reverses onto its dock)
//    GPIO12  XSHUT down-right    (0x32)  front-right, -27 deg, r 100 mm
//    GPIO13  XSHUT forward-left  (0x33)
//    GPIO14  XSHUT forward-right (0x34)
//    BNO085 (default): I2C mode (PS0/PS1 low), addr 0x4A, INT/RST not used.
//    MPU-6050 (env base_mpu6050): AD0 -> GND (addr 0x68), INT not used.
//    Down sensors sit ~50 mm above the floor; forward sensors ~45 mm behind
//    the bumper face (FWD_TOF_OFFSET_MM).
//
//  Bumpers (micro-switch COM -> GND, NO -> GPIO, internal pull-up; pressed = LOW):
//    GPIO15  bumper left
//    GPIO16  bumper right
//
//  Analogue (ADC1, 11 dB attenuation, read with analogReadMilliVolts):
//    GPIO1   battery: PACK+ -- 100k -- GPIO1 -- 22k -- GND   (12.6 V -> 2.27 V)
//    GPIO2   pack NTC: 3V3 -- 10k (1%) -- GPIO2 -- NTC 10k B3950 -- GND
//    GPIO4   charge contacts: CONTACT+ (before the diode) -- 100k -- GPIO4 -- 22k -- GND
//            (add 100 nF from each ADC pin to GND)
//
//  Motor kill switch sense (servo rail AFTER the rocker), read on the ADC:
//    GPIO5   SERVO_RAIL -- 100k -- GPIO5 -- 33k -- GND (+100 nF)   (12.6 V -> 3.13 V)
//            on above MOTOR_ON_V (7 V), off below MOTOR_OFF_V (6 V); see config.h
//
//  Chest light ring (WS2812, 16 LEDs, 5 V; 330R in series with data, 1000 uF across 5 V):
//    GPIO21  data in
// =============================================================================

// Feetech bus UART (Serial1)
#define PIN_SERVO_TX 17
#define PIN_SERVO_RX 18

// I2C
#define PIN_I2C_SDA 8
#define PIN_I2C_SCL 9

// VL53L1X XSHUT, index order = sensor index in firmware (see config.h TOF_*)
#define PIN_XSHUT_DOWN_L 10
#define PIN_XSHUT_DOWN_REAR 11  // index 1 = `drop` c = REAR
#define PIN_XSHUT_DOWN_R 12
#define PIN_XSHUT_FWD_L 13
#define PIN_XSHUT_FWD_R 14

// Bumpers
#define PIN_BUMP_L 15
#define PIN_BUMP_R 16

// Analogue
#define PIN_ADC_BATTERY 1
#define PIN_ADC_NTC 2
#define PIN_ADC_CHARGE 4

// Motor power sense
#define PIN_MOTOR_SENSE 5

// LEDs
#define PIN_LED_RING 21
