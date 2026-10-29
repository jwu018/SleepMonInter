/*
  Night Night — Step 4: integrated overnight logger  (RTC timestamps + microSD CSV + LDC1612)
  Board: Adafruit Feather RP2040 Adalogger   Libraries: RTClib (+ Adafruit BusIO)
  Wiring: Feather STEMMA QT -> DS3231 RTC -> (Grove-to-QT cable) -> Grove LDC1612   [all I2C]
          microSD in the Feather's slot. LiPo on the JST battery port, or USB.

  Behaviour
    * Powers up -> syncs to the RTC -> opens a NEW file named by start time, e.g.
      /S20261026_194500.csv  -> logs SAMPLE_HZ rows per second until stopped.
    * Works WITHOUT the LDC1612 attached (sensor columns left blank), so SD + RTC can be
      demonstrated on their own. A0 is also logged as a stand-in signal (a potentiometer or
      stretch sensor on A0 makes a nice demo; floating A0 just reads noise).
    * Data are flushed to the card every FLUSH_MS, so pulling power loses at most ~1 s.
    * Every DRIFT_CHECK_MS the logger measures how far its millisecond clock has drifted from
      the RTC and writes a "# drift_check" line (timing evidence for the report).
    * If the card errors (bumped/removed) it keeps retrying and resumes in a new file.

  Controls
    BOOT button (GP7): stop logging (closes file safely) / start a new session.
    LED (GP13): short blink every 2 s = logging | solid = stopped | fast blink = SD problem |
                double blink = RTC problem
    Serial (115200, Newline):  s = stop/start   i = status   v = echo every row on/off
                               h = heartbeat line on/off (on by default)
                               m <note> = write a timestamped marker into the file,
                                          e.g. "m B 12 per min" -> "# mark,<time>,elapsed_ms=..,B 12 per min"
                               SET YYYY-MM-DD HH:MM:SS = set RTC (local time)

  Heartbeat (once per second while logging, every 5 s while stopped), e.g.
    [HB] 21:30:05 rtc=21:30:05 | LOGGING /S20261026_213000.csv | rows=125 +25/s missed=0 |
         SD ok | LDC L=18.1500uH f=3736.10kHz range1s=0.0012uH flags=0 | OK
  The last field is OK or a list of WARNings (low row rate, missed samples, RTC/logger clocks
  disagree, SD error, sensor error flags, sensor not oscillating).
*/

#include <Wire.h>
#include <SPI.h>
#include <SD.h>
#include <RTClib.h>
#include "ldc_lite.h"

// ======================= settings =======================
#define FW_VERSION        "0.3"
#define SAMPLE_HZ         25          // rows per second (breathing is < 1 Hz; 25 Hz is plenty)
#define LDC_CHANNEL       0           // 0 = onboard coil (bench test), 1 = external coil / RIP belt
#define LDC_TANK_PF       100.0       // total capacitance across the coil (100 pF onboard)
#define LDC_DRIVE         20          // 0-31; tune with 03_ldc1612_test
#define FLUSH_MS          1000
#define DRIFT_CHECK_MS    600000UL    // 10 minutes
#define STANDIN_PIN       A0
// ========================================================

RTC_DS3231 rtc;
LdcLite ldc;
File logFile;

bool rtcOk = false, sdOk = false, ldcOk = false;
bool logging = false, echoRows = false;
char fileName[40] = "";

// time base: anchor (RTC second boundary) + millis()
uint32_t anchorUnix = 0, anchorMillis = 0;
uint32_t sessionStartMillis = 0;
uint32_t periodUs = 1000000UL / SAMPLE_HZ, nextSampleUs = 0;
uint32_t sampleIdx = 0, rowsWritten = 0, missedSlots = 0, lastFlush = 0;

// drift check state
uint32_t lastDriftCheck = 0; bool driftChecking = false;
uint8_t driftPrevSec = 0; uint32_t driftPrevMillis = 0;

// heartbeat state (stats gathered over the last second)
bool heartbeat = true;
uint32_t lastHb = 0, rowsAtLastHb = 0, missedAtLastHb = 0;
double hbMinL = 1e9, hbMaxL = -1, hbLastL = 0, hbLastF = 0;
uint8_t hbFlagsOr = 0; uint32_t hbBadReads = 0, hbReads = 0;

// ---------------- time helpers ----------------
time_t sdTimeCallback() { return rtcOk ? (time_t)rtc.now().unixtime() : 0; }

// Block (<= ~1.1 s) until the RTC seconds tick over so our ms clock starts exactly on a second.
void anchorToRtc() {
  if (!rtcOk) { anchorUnix = 946684800UL; anchorMillis = millis(); return; }  // 2000-01-01
  uint8_t s0 = rtc.now().second();
  uint32_t t0 = millis();
  while (millis() - t0 < 1500) {
    DateTime n = rtc.now();
    if (n.second() != s0) { anchorMillis = millis(); anchorUnix = n.unixtime(); return; }
  }
  DateTime n = rtc.now(); anchorUnix = n.unixtime(); anchorMillis = millis();
}

uint64_t nowMs() { return (uint64_t)anchorUnix * 1000ULL + (uint32_t)(millis() - anchorMillis); }

void fmtTime(uint64_t ms, char *buf, size_t n, bool withMs = true) {
  DateTime d((uint32_t)(ms / 1000ULL));
  if (withMs)
    snprintf(buf, n, "%04d-%02d-%02d %02d:%02d:%02d.%03u", d.year(), d.month(), d.day(),
             d.hour(), d.minute(), d.second(), (unsigned)(ms % 1000ULL));
  else
    snprintf(buf, n, "%04d-%02d-%02d %02d:%02d:%02d", d.year(), d.month(), d.day(),
             d.hour(), d.minute(), d.second());
}

// ---------------- SD ----------------
bool mountSd() {
  SPI1.setRX(PIN_SD_DAT0_MISO);
  SPI1.setTX(PIN_SD_CMD_MOSI);
  SPI1.setSCK(PIN_SD_CLK);
  sdOk = SD.begin(PIN_SD_DAT3_CS, SPI1);
  if (sdOk) SD.setTimeCallback(sdTimeCallback);   // correct created/modified dates on files
  return sdOk;
}

bool writeLine(const char *s) {
  if (!logFile) return false;
  size_t n = logFile.println(s);
  if (n == 0) { sdOk = false; return false; }
  return true;
}

bool openSession() {
  if (!sdOk && !mountSd()) return false;
  anchorToRtc();
  DateTime d(anchorUnix);
  snprintf(fileName, sizeof fileName, "/S%04d%02d%02d_%02d%02d%02d.csv",
           d.year(), d.month(), d.day(), d.hour(), d.minute(), d.second());
  for (int k = 1; SD.exists(fileName) && k < 100; k++)   // never overwrite
    snprintf(fileName, sizeof fileName, "/S%04d%02d%02d_%02d%02d%02d_%02d.csv",
             d.year(), d.month(), d.day(), d.hour(), d.minute(), d.second(), k);
  logFile = SD.open(fileName, FILE_WRITE);
  if (!logFile) { sdOk = false; return false; }

  char t[32], line[160];
  fmtTime(nowMs(), t, sizeof t, false);
  writeLine("# Night Night respiratory logger, firmware " FW_VERSION);
  snprintf(line, sizeof line, "# start_local,%s", t);                         writeLine(line);
  snprintf(line, sizeof line, "# rtc,%s", rtcOk ? "DS3231 ok" : "MISSING (times are fake)"); writeLine(line);
  snprintf(line, sizeof line, "# sample_rate_hz,%d", SAMPLE_HZ);               writeLine(line);
  if (ldcOk)
    snprintf(line, sizeof line, "# ldc1612,channel %d, tank %.0f pF, drive %d",
             LDC_CHANNEL, (double)LDC_TANK_PF, LDC_DRIVE);
  else
    snprintf(line, sizeof line, "# ldc1612,NOT FOUND (sensor columns blank)");
  writeLine(line);
  writeLine("datetime,elapsed_ms,sample,ldc_raw,ldc_freq_hz,ldc_L_uH,ldc_flags,a0_raw");
  logFile.flush();

  sessionStartMillis = millis();
  sampleIdx = rowsWritten = missedSlots = 0;
  lastFlush = lastDriftCheck = millis();
  driftChecking = false;
  nextSampleUs = micros();
  logging = true;
  rowsAtLastHb = missedAtLastHb = 0;
  lastHb = millis();
  snprintf(line, sizeof line, "Logging to %s", fileName);
  Serial.println(line);
  return true;
}

void closeSession(const char *why) {
  if (logFile) {
    char t[32], line[160];
    fmtTime(nowMs(), t, sizeof t);
    snprintf(line, sizeof line, "# stop,%s,reason=%s,rows=%lu,missed_slots=%lu", t, why,
             (unsigned long)rowsWritten, (unsigned long)missedSlots);
    writeLine(line);
    logFile.close();
  }
  logging = false;
  char msg[120];
  snprintf(msg, sizeof msg, "Stopped (%s). rows=%lu missed=%lu  -> safe to remove the card",
           why, (unsigned long)rowsWritten, (unsigned long)missedSlots);
  Serial.println(msg);
}

// ---------------- sampling ----------------
void takeSample() {
  char t[32], line[160], sens[80] = ",,,";
  uint64_t ms = nowMs();
  fmtTime(ms, t, sizeof t);
  if (ldcOk) {
    LdcLite::Reading r = ldc.read();
    snprintf(sens, sizeof sens, "%lu,%.1f,%.5f,%u", (unsigned long)r.raw, r.freqHz,
             r.inductanceUh, r.flags);
    hbReads++;
    hbFlagsOr |= r.flags;
    if (r.ok) {
      hbLastL = r.inductanceUh; hbLastF = r.freqHz;
      if (r.inductanceUh < hbMinL) hbMinL = r.inductanceUh;
      if (r.inductanceUh > hbMaxL) hbMaxL = r.inductanceUh;
    } else {
      hbBadReads++;
    }
  }
  int a0 = analogRead(STANDIN_PIN);
  snprintf(line, sizeof line, "%s,%lu,%lu,%s,%d", t,
           (unsigned long)(millis() - sessionStartMillis), (unsigned long)sampleIdx, sens, a0);
  if (writeLine(line)) rowsWritten++;
  if (echoRows) Serial.println(line);
}

void driftCheckStep() {
  // Called once per sample while checking; finds the RTC second edge to within half a sample period.
  DateTime n = rtc.now();
  uint32_t m = millis();
  if (n.second() != driftPrevSec && driftPrevMillis != 0) {
    uint32_t edgeMillis = driftPrevMillis + (m - driftPrevMillis) / 2;
    int64_t ours = (int64_t)anchorUnix * 1000 + (int64_t)(uint32_t)(edgeMillis - anchorMillis);
    int64_t theirs = (int64_t)n.unixtime() * 1000;
    char t[32], line[120];
    fmtTime(nowMs(), t, sizeof t);
    snprintf(line, sizeof line, "# drift_check,%s,elapsed_ms=%lu,drift_ms=%ld,resolution_ms=+/-%lu",
             t, (unsigned long)(m - sessionStartMillis), (long)(ours - theirs),
             (unsigned long)(1000 / SAMPLE_HZ / 2));
    writeLine(line);
    Serial.println(line);
    driftChecking = false;
    lastDriftCheck = m;
  }
  driftPrevSec = n.second();
  driftPrevMillis = m;
}

// ---------------- UI ----------------
void updateLed() {
  uint32_t m = millis();
  bool on;
  if (!sdOk)          on = (m / 100) % 2;                                  // fast blink
  else if (!rtcOk)    { uint32_t p = m % 1500; on = p < 100 || (p > 250 && p < 350); }
  else if (logging)   on = (m % 2000) < 40;                                // short blink
  else                on = true;                                           // stopped
  digitalWrite(PIN_LED, on);
}

void printStatus() {
  char t[32], msg[200];
  fmtTime(nowMs(), t, sizeof t);
  snprintf(msg, sizeof msg, "time %s | RTC %s | SD %s | LDC %s | %s %s rows=%lu missed=%lu",
           t, rtcOk ? "ok" : "MISSING", sdOk ? "ok" : "ERROR", ldcOk ? "ok" : "not found",
           logging ? "LOGGING" : "stopped", fileName,
           (unsigned long)rowsWritten, (unsigned long)missedSlots);
  Serial.println(msg);
}

// One self-checking status line per second (every 5 s when stopped).
void heartbeatTick() {
  if (!heartbeat || !Serial) return;   // skip when no computer is listening (on battery)
  uint32_t now = millis();
  uint32_t interval = logging ? 1000 : 5000;
  if (now - lastHb < interval) return;
  uint32_t dtMs = now - lastHb;
  lastHb = now;

  char t[16], rtcStr[16] = "--:--:--", warn[200] = "", line[640];
  DateTime d((uint32_t)(nowMs() / 1000ULL));
  snprintf(t, sizeof t, "%02d:%02d:%02d", d.hour(), d.minute(), d.second());

  // Cross-check: the RTC chip itself vs. the logger's millisecond clock
  if (rtcOk) {
    DateTime r = rtc.now();
    snprintf(rtcStr, sizeof rtcStr, "%02d:%02d:%02d", r.hour(), r.minute(), r.second());
    long diff = (long)r.unixtime() - (long)(nowMs() / 1000ULL);
    if (diff > 1 || diff < -1) strncat(warn, " WARN:rtc/logger clocks differ", sizeof warn - strlen(warn) - 1);
    if (r.year() < 2025) strncat(warn, " WARN:rtc time not set (use SET)", sizeof warn - strlen(warn) - 1);
  } else {
    strncat(warn, " WARN:RTC missing", sizeof warn - strlen(warn) - 1);
  }
  if (!sdOk) strncat(warn, " WARN:SD error", sizeof warn - strlen(warn) - 1);

  char rows[80] = "";
  if (logging) {
    uint32_t dRows = rowsWritten - rowsAtLastHb;
    uint32_t dMiss = missedSlots - missedAtLastHb;
    rowsAtLastHb = rowsWritten; missedAtLastHb = missedSlots;
    float rate = dtMs ? dRows * 1000.0f / dtMs : 0;
    snprintf(rows, sizeof rows, "rows=%lu +%.0f/s missed=%lu",
             (unsigned long)rowsWritten, rate, (unsigned long)missedSlots);
    if (rate < SAMPLE_HZ - 2) strncat(warn, " WARN:row rate low", sizeof warn - strlen(warn) - 1);
    if (dMiss) strncat(warn, " WARN:samples missed this second", sizeof warn - strlen(warn) - 1);
  }

  char sens[120];
  if (!ldcOk) {
    snprintf(sens, sizeof sens, "LDC not found");
  } else if (hbReads && hbBadReads == hbReads) {
    snprintf(sens, sizeof sens, "LDC no valid readings");
    strncat(warn, " WARN:sensor not oscillating", sizeof warn - strlen(warn) - 1);
  } else {
    double range = (hbMaxL >= hbMinL) ? hbMaxL - hbMinL : 0;
    snprintf(sens, sizeof sens, "LDC L=%.4fuH f=%.2fkHz range1s=%.4fuH flags=%u",
             hbLastL, hbLastF / 1000.0, range, hbFlagsOr);
    if (hbFlagsOr) strncat(warn, " WARN:sensor error flags (run 03 test)", sizeof warn - strlen(warn) - 1);
  }
  hbMinL = 1e9; hbMaxL = -1; hbFlagsOr = 0; hbBadReads = hbReads = 0;

  snprintf(line, sizeof line, "[HB] %s rtc=%s | %s %s | %s | SD %s | %s |%s",
           t, rtcStr, logging ? "LOGGING" : "STOPPED", logging ? fileName : "",
           rows, sdOk ? "ok" : "ERROR", sens, warn[0] ? warn : " OK");
  Serial.println(line);
}

void handleSerial() {
  if (!Serial.available()) return;
  String s = Serial.readStringUntil('\n');
  s.trim();
  if (s == "s") { if (logging) closeSession("serial"); else openSession(); }
  else if (s == "i") printStatus();
  else if (s == "v") echoRows = !echoRows;
  else if (s == "h") { heartbeat = !heartbeat; Serial.println(heartbeat ? "heartbeat on" : "heartbeat off"); }
  else if (s == "m" || s.startsWith("m ")) {
    // Timestamped event marker (e.g. start of a paced-breathing segment)
    if (!logging) { Serial.println(F("Not logging - marker not written.")); return; }
    String note = s.length() > 2 ? s.substring(2) : String("mark");
    note.replace(",", ";");                                // keep the CSV comment parseable
    char t[32], line[200];
    fmtTime(nowMs(), t, sizeof t);
    snprintf(line, sizeof line, "# mark,%s,elapsed_ms=%lu,%s", t,
             (unsigned long)(millis() - sessionStartMillis), note.c_str());
    writeLine(line);
    logFile.flush();
    Serial.print(F("MARKED: ")); Serial.println(line + 7);
  }
  else if (s.startsWith("SET ") && rtcOk) {
    int Y, M, D, h, mi, se;
    if (sscanf(s.c_str() + 4, "%d-%d-%d %d:%d:%d", &Y, &M, &D, &h, &mi, &se) == 6) {
      bool was = logging;
      if (was) closeSession("time_set");
      rtc.adjust(DateTime(Y, M, D, h, mi, se));
      anchorToRtc();
      Serial.println(F("RTC set."));
      if (was) openSession();
    }
  } else Serial.println(F("s=stop/start  i=status  v=echo rows  h=heartbeat on/off  m <note>=marker  SET YYYY-MM-DD HH:MM:SS"));
}

void handleButton() {
  static bool last = HIGH; static uint32_t lastChange = 0;
  bool b = digitalRead(PIN_BUTTON);
  if (b != last && millis() - lastChange > 50) {
    lastChange = millis(); last = b;
    if (b == LOW) { if (logging) closeSession("button"); else openSession(); }
  }
}

// ---------------- main ----------------
void setup() {
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  analogReadResolution(12);
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 2000) delay(10);   // don't wait forever on battery

  Wire.begin();
  Wire.setClock(400000);
  rtcOk = rtc.begin(&Wire);
  if (rtcOk && rtc.lostPower()) rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));

  ldc.tankPf = LDC_TANK_PF;
  ldc.idrive = LDC_DRIVE;
  ldcOk = ldc.begin(Wire) && ldc.startChannel(LDC_CHANNEL);
  delay(60);   // first conversion

  mountSd();
  printStatus();
  openSession();
}

void loop() {
  handleSerial();
  handleButton();
  updateLed();
  heartbeatTick();

  if (!logging) {
    // If we stopped because of an SD fault, keep trying to recover every 5 s
    static uint32_t lastRetry = 0;
    if (!sdOk && millis() - lastRetry > 5000) {
      lastRetry = millis();
      if (logFile) logFile.close();
      SD.end(false);
      if (mountSd()) openSession();
    }
    return;
  }

  int32_t late = (int32_t)(micros() - nextSampleUs);
  if (late < 0) return;                        // not time yet
  if (late > (int32_t)periodUs) {              // fell behind (e.g. slow SD flush): skip slots
    uint32_t skip = late / periodUs;
    missedSlots += skip; sampleIdx += skip; nextSampleUs += skip * periodUs;
  }
  nextSampleUs += periodUs;

  takeSample();
  sampleIdx++;

  if (rtcOk && !driftChecking && millis() - lastDriftCheck > DRIFT_CHECK_MS) {
    driftChecking = true; driftPrevMillis = 0;
  }
  if (driftChecking) driftCheckStep();

  if (millis() - lastFlush >= FLUSH_MS) {
    lastFlush = millis();
    logFile.flush();
    if (!sdOk) { closeSession("sd_error"); sdOk = false; }
  }
}
