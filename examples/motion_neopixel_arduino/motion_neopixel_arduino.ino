#include <SoftwareSerial.h>
#include <Adafruit_NeoPixel.h>

#define PIN 6
#define NUMPIXELS 34
#define LOWEST_BRIGHTNESS 10
#define MAX_BRIGHTNESS 155

#define MAX_DISTANCE 175            // cm → minimum brightness
#define FULL_BRIGHTNESS_DISTANCE 50 // cm → maximum brightness

#define BUFFER_SIZE 10

int distanceBuffer[BUFFER_SIZE];
int bufferIndex = 0;
bool bufferFilled = false;

Adafruit_NeoPixel strip(NUMPIXELS, PIN, NEO_GRB + NEO_KHZ800);
SoftwareSerial mySerial(11, 10); // RX, TX

String incomingLine = "";
int currentBrightness = LOWEST_BRIGHTNESS;

//
// ───────────────────────────── SETUP ─────────────────────────────
//

void setup()
{
  Serial.begin(115200);
  mySerial.begin(115200);

  initLEDStrip();
  sendInitialCommand();

  Serial.println("System ready!");
}

//
// ───────────────────────────── LOOP ─────────────────────────────
//

void loop()
{
  readSerialData();
}

//
// ───────────────────────── SERIAL HANDLING ─────────────────────────
//

/**
 * Reads incoming serial data line-by-line.
 */
void readSerialData()
{
  while (mySerial.available() > 0)
  {
    char c = mySerial.read();

    if (c == '\r')
      return;

    if (c == '\n')
    {
      handleLine(incomingLine);
      incomingLine = "";
    }
    else
    {
      incomingLine += c;
    }
  }
}

/**
 * Decides how to process a full received line.
 */
void handleLine(const String &line)
{
  Serial.print("Packet: ");
  Serial.println(line);

  if (line.startsWith("Range "))
  {
    handleDistance(line);
  }
  else if (line == "ON")
  {
    handlePresenceDetected();
  }
}

//
// ───────────────────────── BUSINESS LOGIC ─────────────────────────
//
float smoothedDistance = 0;
void addDistanceReading(int distance)
{
  distanceBuffer[bufferIndex] = distance;
  bufferIndex = (bufferIndex + 1) % BUFFER_SIZE;

  if (bufferIndex == 0)
  {
    bufferFilled = true;
  }
}
int smoothDistance(int newValue)
{
  float alpha = 0.2; // smaller = smoother
  smoothedDistance = alpha * newValue + (1 - alpha) * smoothedDistance;
  return (int)smoothedDistance;
}
/**
 * Extracts distance and updates LED brightness.
 */
void handleDistance(const String &line)
{
  int rawDistance = extractDistance(line);
  addDistanceReading(rawDistance);
  if (rawDistance < 10)
  {
    return;
  }
  int distance = getFilteredDistance();
  // int distance = smoothDistance(getFilteredDistance());
  Serial.print("Distance: ");
  Serial.print(distance);
  Serial.println(" cm");

  int newBrightness = calculateBrightness(distance);

  updateBrightness(newBrightness);
}

/**
 * Extracts distance value from "Range XXX" string.
 */
int extractDistance(const String &line)
{
  return line.substring(6).toInt();
}
int getFilteredDistance()
{
  int size = bufferFilled ? BUFFER_SIZE : bufferIndex;

  if (size == 0)
    return MAX_DISTANCE;

  // Copy buffer (so we don't destroy original order)
  int temp[size];
  for (int i = 0; i < size; i++)
  {
    temp[i] = distanceBuffer[i];
  }

  // Sort (simple bubble sort, fine for 10 elements)
  for (int i = 0; i < size - 1; i++)
  {
    for (int j = 0; j < size - i - 1; j++)
    {
      if (temp[j] > temp[j + 1])
      {
        int t = temp[j];
        temp[j] = temp[j + 1];
        temp[j + 1] = t;
      }
    }
  }

  // Trim outliers (remove 2 smallest + 2 largest if possible)
  int start = (size > 6) ? 2 : 0;
  int end = (size > 6) ? size - 2 : size;

  long sum = 0;
  int count = 0;

  for (int i = start; i < end; i++)
  {
    sum += temp[i];
    count++;
  }

  return sum / count;
}
/**
 * Maps distance → brightness.
 *
 * Rules:
 * - >= 250 cm → LOWEST_BRIGHTNESS
 * - <= 100 cm → MAX_BRIGHTNESS
 * - Linear interpolation between
 */
int calculateBrightness(int distance)
{
  if (distance >= MAX_DISTANCE)
  {
    return LOWEST_BRIGHTNESS;
  }

  if (distance <= FULL_BRIGHTNESS_DISTANCE)
  {
    return MAX_BRIGHTNESS;
  }

  // Linear interpolation
  float ratio = (float)(MAX_DISTANCE - distance) / (MAX_DISTANCE - FULL_BRIGHTNESS_DISTANCE);

  int brightness = LOWEST_BRIGHTNESS + ratio * (MAX_BRIGHTNESS - LOWEST_BRIGHTNESS);

  return constrain(brightness, LOWEST_BRIGHTNESS, MAX_BRIGHTNESS);
}

//
// ───────────────────────── LED CONTROL ─────────────────────────
//

/**
 * Initializes LED strip to default state.
 */
void initLEDStrip()
{
  strip.begin();
  setAllPixelsWhite();
  strip.setBrightness(LOWEST_BRIGHTNESS);
  strip.show();
}

/**
 * Updates brightness only if it changed.
 */
void updateBrightness(int newBrightness)
{
  if (newBrightness == currentBrightness)
    return;

  currentBrightness = newBrightness;

  Serial.print("Brightness: ");
  Serial.println(currentBrightness);

  strip.setBrightness(currentBrightness);
  strip.show();
}

/**
 * Sets all LEDs to white.
 */
void setAllPixelsWhite()
{
  for (int i = 0; i < NUMPIXELS; i++)
  {
    strip.setPixelColor(i, strip.Color(255, 255, 255));
  }
}

//
// ───────────────────────── EVENTS ─────────────────────────
//

/**
 * Called when presence is detected.
 */
void handlePresenceDetected()
{
  Serial.println("Presence detected!");
}

//
// ───────────────────────── SERIAL TX ─────────────────────────
//

/**
 * Sends initialization hex command to sensor/module.
 */
void sendInitialCommand()
{
  String hex = "FDFCFBFA0800120000006400000004030201";
  sendHexData(hex);
}

/**
 * Converts hex string to bytes and sends via serial.
 */
void sendHexData(const String &hexString)
{
  int len = hexString.length();
  byte buffer[len / 2];

  for (int i = 0; i < len; i += 2)
  {
    buffer[i / 2] = strtoul(hexString.substring(i, i + 2).c_str(), NULL, 16);
  }

  mySerial.write(buffer, sizeof(buffer));
}