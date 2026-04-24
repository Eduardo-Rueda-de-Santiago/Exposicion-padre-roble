from machine import Pin, PWM
import time

# Configurar el pin PWM en el GPIO 18
# La frecuencia de 1000Hz es ideal para evitar parpadeos en LEDs
led_strip = PWM(Pin(22), freq=1000)

while True:
    # Aumentar brillo (rango 0 a 1023)
    for brightness in range(0, 1024, 5):
        led_strip.duty(brightness)
        time.sleep(0.01)
        
    # Disminuir brillo
    for brightness in range(1023, -1, -5):
        led_strip.duty(brightness)
        time.sleep(0.01)
