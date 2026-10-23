#pragma once
// Feetech STS bus on top of Feetech's own FTServo library (SMS_STS class).
//
// What this adds to the library:
//  * every read is time-boxed in MICROseconds (library default: 10 ms per byte);
//  * optional TX-echo handling: some half-duplex adapters copy our own bytes
//    back onto RX, which the library cannot cope with. STS_BUS_ECHO selects
//    no-echo / echo / auto-detect (ping an ID nobody has and look for our
//    own packet coming back).
//
// Register map: Feetech "ST3215 Memory Table Parsing V3.7" (the regs.csv /
// regs.xls in the coordinator's download), FTServo 2.0.0 SMS_STS.h, and
// HuggingFace LeRobot's STS_SMS_SERIES_CONTROL_TABLE (cites the Feetech
// SMS/STS e-manual). All three agree on every address used here:
//    5  ID                         (EEPROM)
//   14  max input voltage, 0.1 V   (EEPROM)
//   16  max torque, 0.1 %          (EEPROM; copied to 48 at power-up)
//   33  operating mode: 0 position, 1 constant speed (wheel), 2 PWM, 3 step (EEPROM)
//   40  torque enable: 0 off, 1 on, 128 = "current position becomes 2048"
//   41  acceleration, 100 steps/s^2
//   42  goal position (steps, bit 15 = sign)
//   46  goal speed (steps/s, 0..3400, bit 15 = direction)
//   48  torque limit, 0..1000 (= 0.1 %; the V3.7 sheet says "1%" in the unit
//       column but gives 0..1000 and the EEPROM twin at 16 says 0.1 %)
//   55  EEPROM lock: 0 = unlocked (writes persist), 1 = locked
//   56  present position (0..4095, single turn)
//   58  present speed (steps/s, bit 15 = sign)
//   60  present load (0.1 % duty, bit 10 = sign)
//   62  present voltage (0.1 V)   63 present temperature (deg C)
//   65  status: b0 voltage b1 sensor b2 temperature b3 current b4 angle b5 overload
//   66  moving flag   69 present current (6.5 mA units)
#include <Arduino.h>
#include <SCServo.h>

struct ServoFeedback {
  bool ok = false;
  int pos = 0;        // 0..4095
  int speed = 0;      // steps/s, signed
  int load = 0;       // 0.1 %, signed
  int voltage_dv = 0; // 0.1 V
  int temp_c = 0;
  int status = 0;     // reg 65
  int current = 0;    // 6.5 mA units
};

class StsBus : public SMS_STS {
 public:
  void begin(HardwareSerial& port, uint32_t baud, int rx_pin, int tx_pin, int echo_mode);
  // Ping an unused ID and see whether our own bytes come back (mode 2 only).
  void detectEcho();
  bool echo() const { return echo_; }

  // Presence check. Not a PING: our own echoed PING packet parses as a valid
  // PING reply, so read regs 3..5 instead (3-byte reply, last byte = ID),
  // which an echo can never imitate.
  bool ping(uint8_t id);
  // One 15-byte read (regs 56..70): position, speed, load, voltage, temp, status, current.
  bool feedback(uint8_t id, ServoFeedback& fb);
  int readReg8(uint8_t id, uint8_t reg);   // -1 on failure
  int readReg16(uint8_t id, uint8_t reg);  // -1 on failure
  bool writeReg8(uint8_t id, uint8_t reg, uint8_t v);
  bool writeReg16(uint8_t id, uint8_t reg, uint16_t v);
  // EEPROM write guarded by unlock/lock (only call when the value differs).
  bool writeEeprom8(uint8_t id, uint8_t reg, uint8_t v);
  bool writeEeprom16(uint8_t id, uint8_t reg, uint16_t v);
  // Broadcast (ID 0xFE, no reply): torque off on every servo on the bus.
  void broadcastTorqueOff() { writeByte(0xFE, 40, 0); }
  // Wheel speeds for several servos in one sync-write packet (no reply).
  void syncSpeeds(uint8_t* ids, uint8_t n, int16_t* speeds, uint8_t acc);
  bool torque(uint8_t id, bool on) { return writeReg8(id, 40, on ? 1 : 0); }
  bool goalPos(uint8_t id, int pos, int speed, uint8_t acc) {
    return WritePosEx(id, (s16)pos, (u16)speed, acc) == 1;
  }

  uint32_t txPackets = 0, rxFailures = 0;

 protected:
  int writeSCS(unsigned char* nDat, int nLen) override;
  int writeSCS(unsigned char bDat) override;
  int readSCS(unsigned char* nDat, int nLen) override;
  int readSCS(unsigned char* nDat, int nLen, unsigned long TimeOut) override;
  void rFlushSCS() override;
  void wFlushSCS() override;

 private:
  int readTimed(unsigned char* d, int n, uint32_t first_us, uint32_t gap_us);
  HardwareSerial* port_ = nullptr;
  int echo_mode_ = 2;
  bool echo_ = false;
  uint8_t sent_[96];
  int sent_n_ = 0;
};
