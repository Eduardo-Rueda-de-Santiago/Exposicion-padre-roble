from machine import UART, Pin
import uasyncio as asyncio
import time

time.sleep(2)  # wait before starting UART

led = Pin(2, Pin.OUT)
uart = UART(2, baudrate=115200, tx=17, rx=16, timeout=10, rxbuf=1024)

# LED heartbeat task (runs forever)
async def heartbeat_task():
    while True:
        led.value(1)
        await asyncio.sleep_ms(500)
        led.value(0)
        await asyncio.sleep_ms(500)

# UART reading task
async def uart_task():
    while True:
        try:
            if uart.any():
                data = uart.read(256)  # read max 256 bytes to avoid blocking on large bursts
                if data is not None:
                    print(data)
        except Exception as e:
            print("UART error:", e)
        await asyncio.sleep_ms(10)  # tighter poll interval

# Main entry
async def main():
    print("Running human detection software")
    asyncio.create_task(heartbeat_task())
    asyncio.create_task(uart_task())
    while True:
        await asyncio.sleep_ms(1000)

# Run event loop
asyncio.run(main())