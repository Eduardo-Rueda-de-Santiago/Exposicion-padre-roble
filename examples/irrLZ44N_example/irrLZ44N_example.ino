// Definir el pin PWM (debe tener el símbolo ~)
const int ledPin = 9; 

void setup() {
  // Configurar el pin como salida
  pinMode(ledPin, OUTPUT);
}

void loop() {
  // Aumentar el brillo de 0 a 255
  for (int brightness = 0; brightness <= 255; brightness++) {
    analogWrite(ledPin, brightness);
    delay(10); // Ajusta este valor para cambiar la velocidad del desvanecimiento
  }

  // Disminuir el brillo de 255 a 0
  for (int brightness = 255; brightness >= 0; brightness--) {
    analogWrite(ledPin, brightness);
    delay(10);
  }
}
