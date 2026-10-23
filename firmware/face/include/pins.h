#pragma once
// =============================================================================
//  FACE ESP32-S3 -- every GPIO in one place.
//  Board: ESP32-S3-DevKitC-1 N8R2. Change pins here only.
//  (Avoid: GPIO0/3/45/46 straps, 19/20 USB, 26..32 flash/PSRAM, 33..37,
//   38/48 on-board RGB LED, 43/44 UART0.)
//
//  WIRING
//  ------------------------------------------------------------------------
//  Two GC9A01 1.28" 240x240 round LCDs, one SPI bus (SPI2/FSPI):
//    GPIO12  SCL/SCK   -> both LCDs   (FSPI IO_MUX pin: needed for 80 MHz)
//    GPIO11  SDA/MOSI  -> both LCDs   (FSPI IO_MUX pin)
//    GPIO8   DC        -> both LCDs
//    GPIO14  RST       -> both LCDs
//    GPIO10  CS        -> LEFT eye  (robot's left = the viewer's right)
//    GPIO9   CS        -> RIGHT eye
//    GPIO7   BLK       -> both backlights through a logic-level N-MOSFET
//                         (or straight to BLK if the module has its own
//                          transistor; two modules draw ~40 mA)
//    VCC 3V3, GND. Keep SPI wires short (< 10 cm) for 80 MHz.
//
//  Head power: the 3 x MG90S (ears + visor/shutter), the mic amp and the LCDs
//  run from the HEAD 5 V rail: its own 5 V 3 A buck from the pack via a
//  polyfuse, NOT the Pi's buck. Common GND with this board.
//
//  Visor (MG90S micro servo on the brow slider) + visor-UP limit switch:
//    GPIO4   servo signal (head 5 V rail, common GND)
//    GPIO5   switch: COM -> GND, NO -> GPIO5 (pull-up). CLOSED = visor fully UP.
//
//  Ears (2 x MG90S, head 5 V rail):
//    GPIO15  left ear signal
//    GPIO16  right ear signal
//
//  Touch pad (TTP223 module, default jumpers: active HIGH, momentary):
//    GPIO6   OUT     (module VCC 3V3)
//
//  Head-height forward range sensor (VL53L1X, PROTOCOL 2 `range`): catches
//  table edges and benchtops the lidar plane (138 mm) can't see.
//    GPIO17  I2C SDA  (2.2k pull-up to 3V3)
//    GPIO18  I2C SCL  (2.2k pull-up to 3V3)
//    GPIO21  XSHUT    (lets the firmware reset a hung sensor)
//    VIN 3V3, GND. Default address 0x29 (only device on this bus).
// =============================================================================

#define PIN_LCD_SCLK 12
#define PIN_LCD_MOSI 11
#define PIN_LCD_DC 8
#define PIN_LCD_RST 14
#define PIN_LCD_CS_LEFT 10
#define PIN_LCD_CS_RIGHT 9
#define PIN_LCD_BL 7

#define PIN_VISOR_SERVO 4
#define PIN_VISOR_UP_SW 5

#define PIN_EAR_LEFT 15
#define PIN_EAR_RIGHT 16

#define PIN_TOUCH 6

#define PIN_I2C_SDA 17
#define PIN_I2C_SCL 18
#define PIN_HEAD_TOF_XSHUT 21
