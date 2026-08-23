/*
 * power_relay.ino
 *
 * Companion firmware for Story 26.7 (EPIC 5: Device Power-Cycle Recovery).
 * Drives a relay module (1 or more channels) to cut/restore VBUS power to
 * one or more USB devices, on command from the host over serial. Nothing
 * in this firmware is device-specific - it just switches power on request.
 *
 * Board support: ESP32 or ESP8266 (e.g. NodeMCU V2) dev boards both work -
 * this uses only plain Arduino core APIs (Serial/pinMode/digitalWrite),
 * nothing platform-specific. Select the matching board profile in the
 * Arduino IDE before flashing; default GPIO pins below are chosen
 * per-platform automatically, but can be overridden if wired differently.
 *
 * Protocol (plain text lines, one command/response pair per cycle):
 *   host -> board:  CYCLE <channel> <off_seconds>\n   e.g. "CYCLE 1 15\n"
 *   board -> host:  OK\n                               on success
 *                   ERR <reason>\n                      on bad input
 *
 *   host -> board:  ID\n
 *   board -> host:  BTCMESH-RELAY <chip_id>\n           <chip_id> is a
 *                                                        hardware-derived
 *                                                        ID, stable across
 *                                                        reboots, unique
 *                                                        per physical board
 *
 * The ID command (Issue 37 follow-up, project/issues.txt) lets the host
 * positively identify this specific board - not just "a relay board of
 * some kind" - via a proper identity response instead of repurposing the
 * generic unknown-command error text. See transport/power_control.py's
 * probe_relay_board_id() for the host side.
 *
 * See transport/power_control.py's SerialRelayPowerControl for the host
 * side, and project/plans/story_26_7.md for the full design.
 */

// TinyTronics 5VRELHL (5V, runs off the same USB 5V as the ESP32/ESP8266
// board - no separate PSU needed). Has a jumper labeled "H"/"L" to select
// active-high or active-low - confirmed by real end-to-end testing
// (power_cycle() actually toggling the physical relay, not just a manual
// touch test) that jumper on "H" matches ACTIVE_LOW false. If using a
// different module, verify the same way: run an actual power_cycle()
// end-to-end and watch the relay respond, rather than trusting a jumper
// label or a manual IN-pin touch test alone - both can be misleading.
#define ACTIVE_LOW false

// Default GPIO pins, chosen per-platform. A single device/channel is the
// normal case (see story_26_7.md) - RELAY2_PIN is only used if you're
// controlling a second device from this same board.
#if defined(ARDUINO_ARCH_ESP32)
  #define RELAY1_PIN 26
  #define RELAY2_PIN 27
#elif defined(ARDUINO_ARCH_ESP8266)
  // NodeMCU V2/V3 labeled pins D1/D2 - safe general-purpose GPIOs with no
  // boot-mode constraints (unlike D0/D3/D4/D8 - GPIO16/0/2/15 - which
  // affect boot behavior and should be avoided for this purpose).
  #define RELAY1_PIN 5  // D1
  #define RELAY2_PIN 4  // D2
#else
  #error "Unrecognized board - define RELAY1_PIN/RELAY2_PIN manually for your platform"
#endif

#define BAUD_RATE 115200
#define MAX_OFF_SECONDS 120

void relayOn(int pin) {
  digitalWrite(pin, ACTIVE_LOW ? LOW : HIGH);
}

void relayOff(int pin) {
  digitalWrite(pin, ACTIVE_LOW ? HIGH : LOW);
}

void setup() {
  Serial.begin(BAUD_RATE);
  pinMode(RELAY1_PIN, OUTPUT);
  pinMode(RELAY2_PIN, OUTPUT);
  relayOn(RELAY1_PIN);
  relayOn(RELAY2_PIN);
}

int pinForChannel(int channel) {
  if (channel == 1) return RELAY1_PIN;
  if (channel == 2) return RELAY2_PIN;
  return -1;
}

// Hardware-derived, factory-programmed per-chip ID - stable across
// reboots/re-flashes, genuinely unique per physical board, and needs no
// WiFi peripheral initialization (ESP.getEfuseMac()/getChipId() read
// eFuse/OTP storage directly), keeping this firmware's "plain Arduino
// core APIs only" footprint intact.
String getBoardId() {
#if defined(ARDUINO_ARCH_ESP32)
  uint64_t chipid = ESP.getEfuseMac();
  char buf[13];
  snprintf(buf, sizeof(buf), "%04X%08X",
           (uint16_t)(chipid >> 32), (uint32_t)chipid);
  return String(buf);
#elif defined(ARDUINO_ARCH_ESP8266)
  char buf[9];
  snprintf(buf, sizeof(buf), "%08X", ESP.getChipId());
  return String(buf);
#endif
}

void handleLine(String line) {
  line.trim();

  if (line == "ID") {
    Serial.print("BTCMESH-RELAY ");
    Serial.println(getBoardId());
    return;
  }

  int firstSpace = line.indexOf(' ');
  if (firstSpace == -1 || line.substring(0, firstSpace) != "CYCLE") {
    Serial.println("ERR unknown command");
    return;
  }

  int secondSpace = line.indexOf(' ', firstSpace + 1);
  if (secondSpace == -1) {
    Serial.println("ERR malformed command");
    return;
  }

  int channel = line.substring(firstSpace + 1, secondSpace).toInt();
  int offSeconds = line.substring(secondSpace + 1).toInt();

  int pin = pinForChannel(channel);
  if (pin == -1) {
    Serial.println("ERR invalid channel");
    return;
  }
  if (offSeconds <= 0 || offSeconds > MAX_OFF_SECONDS) {
    Serial.println("ERR invalid off_seconds");
    return;
  }

  relayOff(pin);
  delay((unsigned long)offSeconds * 1000UL);
  relayOn(pin);

  Serial.println("OK");
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    handleLine(line);
  }
}
