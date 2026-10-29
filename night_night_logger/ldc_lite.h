/*
  ldc_lite.h — minimal LDC1612 driver for the Seeed Grove 2-Channel Inductive Sensor
  Register values mirror Seeed's Seeed_LDC1612 library (known to work on this board), but
  with a slower, higher-resolution conversion suited to breathing (~0.1-1 Hz) and with the
  frequency/inductance math exposed.

  Key relations (TI LDC1612 datasheet):
    f_ref    = 40 MHz / FREF_DIV           (Seeed board runs the LDC from a 40 MHz clock)
    f_sensor = FIN_DIV * f_ref * DATA / 2^28
    L        = 1 / ((2*pi*f_sensor)^2 * C)  C = total tank capacitance in parallel with the coil
    conversion time = (RCOUNT*16 + 4) / f_ref
*/
#pragma once
#include <Arduino.h>
#include <Wire.h>

class LdcLite {
public:
  // --- settings you may want to change ---
  uint8_t  addr      = 0x2B;   // 0x2A if the ADDR pad is pulled low
  uint8_t  finDiv    = 2;      // 2 is valid for sensor frequencies up to 10 MHz
  uint8_t  frefDiv   = 2;      // 40 MHz / 2 = 20 MHz reference
  uint16_t rcount    = 31250;  // (31250*16+4)/20 MHz = 25 ms per conversion (~40 S/s)
  uint16_t settle    = 64;     // LC settle cycles before each conversion
  uint8_t  idrive    = 20;     // 0..31 sensor drive current code (Seeed default = 20)
  float    tankPf    = 100.0;  // total capacitance across the coil, in pF

  struct Reading {
    uint32_t raw = 0;      // 28-bit conversion result
    uint8_t  flags = 0;    // bit3 under-range, bit2 over-range, bit1 watchdog, bit0 amplitude
    double   freqHz = 0;
    double   inductanceUh = 0;
    bool     ok = false;
  };

  bool begin(TwoWire &w = Wire) {
    _w = &w;
    uint16_t mfg = 0, dev = 0;
    if (!read16(0x7E, mfg) || !read16(0x7F, dev)) return false;
    _mfg = mfg; _dev = dev;
    return mfg == 0x5449 && (dev == 0x3054 || dev == 0x3055);  // "TI", LDC1612/1614
  }
  uint16_t manufacturerId() const { return _mfg; }
  uint16_t deviceId() const { return _dev; }

  // Configure continuous conversion on one channel (0 = onboard coil, 1 = external coil).
  bool startChannel(uint8_t ch) {
    if (ch > 1) return false;
    _ch = ch;
    bool ok = true;
    ok &= write16(0x1C, 0x8000);                              // reset device
    delay(5);
    ok &= write16(0x1A, 0x2001);                             // CONFIG: sleep while we set up
    ok &= write16(0x08 + ch, rcount);                         // RCOUNTx
    ok &= write16(0x10 + ch, settle);                         // SETTLECOUNTx
    ok &= write16(0x0C + ch, 0x0000);                         // OFFSETx
    ok &= write16(0x14 + ch, (uint16_t)(finDiv << 12) | frefDiv);  // CLOCK_DIVIDERSx
    ok &= write16(0x1E + ch, (uint16_t)(idrive & 0x1F) << 11);     // DRIVE_CURRENTx
    ok &= write16(0x19, 0x1801);                              // ERROR_CONFIG: amp errors -> data, DRDY -> INTB
    ok &= write16(0x1B, 0x020D);                              // MUX_CONFIG: single ch, deglitch 10 MHz
    // CONFIG: ACTIVE_CHAN | RP_OVERRIDE | AUTO_AMP_DIS | REF_CLK_SRC(ext 40 MHz) | reserved=1 ; wake up
    ok &= write16(0x1A, (uint16_t)(ch << 14) | 0x1601);
    return ok;
  }

  // Re-apply drive current live (useful while tuning the belt)
  bool setDrive(uint8_t code) { idrive = code & 0x1F; return write16(0x1E + _ch, (uint16_t)idrive << 11); }

  Reading read() {
    Reading r;
    uint16_t msb, lsb;
    if (!read16(0x00 + 2 * _ch, msb) || !read16(0x01 + 2 * _ch, lsb)) return r;  // MSB first
    r.flags = msb >> 12;
    r.raw = ((uint32_t)(msb & 0x0FFF) << 16) | lsb;
    double fref = 40.0e6 / frefDiv;
    r.freqHz = (double)finDiv * fref * (double)r.raw / 268435456.0;
    if (r.freqHz > 0 && tankPf > 0) {
      double w = 2.0 * PI * r.freqHz;
      r.inductanceUh = 1.0 / (w * w * tankPf * 1e-12) * 1e6;
    }
    r.ok = (r.raw != 0 && r.raw != 0x0FFFFFFF);
    return r;
  }

  // STATUS register (0x18): bit11 amplitude-high, bit10 amplitude-low, bit9 zero count
  uint16_t status() { uint16_t s = 0; read16(0x18, s); return s; }

  static void describeFlags(uint8_t flags, Print &out) {
    if (flags & 0x8) out.print(F(" UNDER-RANGE"));
    if (flags & 0x4) out.print(F(" OVER-RANGE"));
    if (flags & 0x2) out.print(F(" WATCHDOG(no oscillation?)"));
    if (flags & 0x1) out.print(F(" AMPLITUDE(adjust drive)"));
  }

private:
  TwoWire *_w = nullptr;
  uint8_t _ch = 0;
  uint16_t _mfg = 0, _dev = 0;

  bool write16(uint8_t reg, uint16_t v) {
    _w->beginTransmission(addr);
    _w->write(reg);
    _w->write((uint8_t)(v >> 8));
    _w->write((uint8_t)(v & 0xFF));
    return _w->endTransmission() == 0;
  }
  bool read16(uint8_t reg, uint16_t &v) {
    _w->beginTransmission(addr);
    _w->write(reg);
    if (_w->endTransmission(false) != 0) return false;
    if (_w->requestFrom(addr, (uint8_t)2) != 2) return false;
    v = ((uint16_t)_w->read() << 8) | _w->read();
    return true;
  }
};
