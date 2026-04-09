import neopixel
import machine 
import time

# 32 LED strip connected to pin 21.
n = neopixel.NeoPixel(machine.Pin(21), 32)

offset = 0

while True:

    # Draw a red gradient.
    for i in range(32):
        num = i + offset
        if num >= 32:
            num -= 32
        n[num] = (i * 2, i *2, i*2)
        
    offset += 1
    
    if offset >= 32:
        offset = 0

    # Update the strip.
    n.write()
    time.sleep_ms(15)
