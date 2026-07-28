/*
 * power_relay.ino
 *
 * Companion firmware for Story 26.7 (EPIC 5: Device Power-Cycle Recovery).
 * Drives a 2-channel relay module to cut/restore VBUS power to two
 * Meshtastic USB devices, on command from the host over serial.
 *
 * Protocol (plain text lines, one command/response pair per cycle):
 *   host -> board:  CYCLE <channel> <off_seconds>\n   e.g. "CYCLE 1 15\n"
 *   board -> host:  OK\n                               on success
 *                   ERR <reason>\n                      on bad input
 *
 * See transport/power_control.py's SerialRelayPowerControl for the host
 * side, and project/plans/story_26_7.md (via humming-mixing-hammock plan)
 * for the full design.
 */

// Most cheap 2-channel relay modules trigger the relay when the input pin
// is driven LOW. Flip this to false if your module is active-HIGH instead
// (check its datasheet/silkscreen).
#define ACTIVE_LOW true

// Adjust to match your ESP32 board's wiring.
#define RELAY1_PIN 26
#define RELAY2_PIN 27

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

void handleLine(String line) {
  line.trim();

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
