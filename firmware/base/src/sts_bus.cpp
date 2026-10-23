#include "sts_bus.h"

#include "config.h"

void StsBus::begin(HardwareSerial& port, uint32_t baud, int rx_pin, int tx_pin, int echo_mode) {
  port_ = &port;
  pSerial = &port;  // the library writes through this pointer
  echo_mode_ = echo_mode;
  echo_ = (echo_mode == 1);
  port.setRxBufferSize(512);
  port.begin(baud, SERIAL_8N1, rx_pin, tx_pin);
  port.setTimeout(0);
  IOTimeOut = 2;  // library ms timeout, only used if a path bypasses our overrides
}

// ---- byte layer --------------------------------------------------------------

int StsBus::writeSCS(unsigned char* d, int n) {
  if (!d || n <= 0) return 0;
  for (int i = 0; i < n && sent_n_ < (int)sizeof(sent_); i++) sent_[sent_n_++] = d[i];
  return port_->write(d, n);
}

int StsBus::writeSCS(unsigned char b) { return writeSCS(&b, 1); }

void StsBus::rFlushSCS() {
  while (port_->read() != -1) {
  }
  sent_n_ = 0;
}

void StsBus::wFlushSCS() {
  port_->flush();  // wait until the last stop bit has left the UART
  txPackets++;
  if (echo_ && sent_n_ > 0) {
    // The echo is already (nearly) all in: allow ~2 byte times + 150 us.
    uint8_t junk[sizeof(sent_)];
    readTimed(junk, sent_n_, 20 * sent_n_ + 150, 150);
  }
  sent_n_ = 0;
}

int StsBus::readTimed(unsigned char* d, int n, uint32_t first_us, uint32_t gap_us) {
  int got = 0;
  uint32_t t0 = micros();
  uint32_t limit = first_us;
  while (got < n) {
    const int c = port_->read();
    if (c >= 0) {
      if (d) d[got] = (unsigned char)c;
      got++;
      t0 = micros();
      limit = gap_us;
    } else if ((uint32_t)(micros() - t0) > limit) {
      break;
    }
  }
  return got;
}

int StsBus::readSCS(unsigned char* d, int n) {
  return readTimed(d, n, STS_BYTE_TIMEOUT_US, STS_BYTE_TIMEOUT_US);
}

int StsBus::readSCS(unsigned char* d, int n, unsigned long timeout_ms) {
  return readTimed(d, n, timeout_ms * 1000UL, timeout_ms * 1000UL);
}

// ---- helpers -------------------------------------------------------------------

void StsBus::detectEcho() {
  if (echo_mode_ != 2) {
    echo_ = (echo_mode_ == 1);
    return;
  }
  // PING to ID 0xFD: no servo has it (IDs are 1..4), so anything that comes
  // back is our own packet.
  const uint8_t id = 0xFD;
  uint8_t pkt[6] = {0xFF, 0xFF, id, 2, 0x01, 0};
  pkt[5] = (uint8_t)~(id + 2 + 0x01);
  while (port_->read() != -1) {
  }
  port_->write(pkt, sizeof pkt);
  port_->flush();
  uint8_t back[6];
  const int n = readTimed(back, 6, 600, 200);
  echo_ = (n == 6 && memcmp(back, pkt, 6) == 0);
}

bool StsBus::ping(uint8_t id) {
  uint8_t b[3];
  if (Read(id, 3, b, 3) != 3) return false;
  return b[2] == id;  // reg 5 = ID
}

bool StsBus::feedback(uint8_t id, ServoFeedback& fb) {
  fb.ok = false;
  if (FeedBack(id) < 0) {
    rxFailures++;
    return false;
  }
  fb.pos = ReadPos(-1);
  fb.speed = ReadSpeed(-1);
  fb.load = ReadLoad(-1);
  fb.voltage_dv = ReadVoltage(-1);
  fb.temp_c = ReadTemper(-1);
  fb.current = ReadCurrent(-1);
  fb.status = getState();  // error byte of the reply packet (same bits as reg 65)
  fb.ok = true;
  return true;
}

int StsBus::readReg8(uint8_t id, uint8_t reg) {
  const int v = readByte(id, reg);
  if (v < 0) rxFailures++;
  return v;
}

int StsBus::readReg16(uint8_t id, uint8_t reg) {
  const int v = readWord(id, reg);
  if (v < 0) rxFailures++;
  return v;
}

bool StsBus::writeReg8(uint8_t id, uint8_t reg, uint8_t v) { return writeByte(id, reg, v) == 1; }

bool StsBus::writeReg16(uint8_t id, uint8_t reg, uint16_t v) { return writeWord(id, reg, v) == 1; }

bool StsBus::writeEeprom8(uint8_t id, uint8_t reg, uint8_t v) {
  bool ok = writeReg8(id, 55, 0);  // unlock
  ok = writeReg8(id, reg, v) && ok;
  ok = writeReg8(id, 55, 1) && ok;  // lock again
  return ok;
}

bool StsBus::writeEeprom16(uint8_t id, uint8_t reg, uint16_t v) {
  bool ok = writeReg8(id, 55, 0);
  ok = writeReg16(id, reg, v) && ok;
  ok = writeReg8(id, 55, 1) && ok;
  return ok;
}

void StsBus::syncSpeeds(uint8_t* ids, uint8_t n, int16_t* speeds, uint8_t acc) {
  uint8_t accs[8];
  int16_t sp[8];
  if (n > 8) n = 8;
  for (int i = 0; i < n; i++) {
    accs[i] = acc;
    sp[i] = speeds[i];  // the library rewrites the array into sign-magnitude
  }
  SyncWriteSpe(ids, n, sp, accs);
}
