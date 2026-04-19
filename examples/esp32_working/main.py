import time

from machine import Pin, Timer

led = Pin(2, Pin.OUT)
timer = Timer(0)
toggle = 1


def blink(timer):
    global toggle
    if toggle == 1:
        led.value(0)
        toggle = 0
    else:
        led.value(1)
        toggle = 1


timer.init(freq=2, mode=Timer.PERIODIC, callback=blink)
