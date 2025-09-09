import network, espnow, _thread
from machine import I2C, Pin
from time import sleep_ms
from lcd_I2C import I2cLcd
from pins import SC, SD
import binascii

try:    
    i2c = I2C(0, scl=Pin(SC), sda=Pin(SD), freq=400000)
    lcd = I2cLcd(i2c, (i2c.scan() or [0x27])[0], 2, 16)
    lcd.clear()
    lcd.putstr("System Online")
    lcd.move_to(len("System Online") if len("System Online") < 16 else 15, 0)
    lcd.blink_cursor_on()
    lcd_available = True
except Exception as e:
    print("LCD not available: ", e)
    lcd_available = False
    
w0 = network.WLAN(network.STA_IF)
w0.active(True)

mac = w0.config('mac')
print("Device MAC:", binascii.hexlify(mac, ':').decode())

e = espnow.ESPNow()
e.active(True)

# Shared queue and lock
lcd_queue = []
lcd_mem = ["", ""]
lcd_lock = _thread.allocate_lock()

def pad16(text):
    return (text[:16] + " " * 16)[:16]

def lcd_worker():
    """Worker thread that updates the LCD from queue messages."""
    global lcd_mem
    while True:
        msg = None
        with lcd_lock:
            if lcd_queue:
                msg = lcd_queue.pop(0)
        if msg and lcd_available:
            try:
                line1, line2 = msg
                print("Got request!")
                print(line1)
                print(line2)
                if line1 == "NOCHANGE":
                    line1 = lcd_mem[0]
                if line2 == "NOCHANGE":
                    line2 = lcd_mem[1]
                lcd.move_to(0, 0)
                lcd.putstr(pad16(line1[:16] if line1 else ""))
                lcd.move_to(0, 1)
                lcd.putstr(pad16(line2[:16] if line2 else ""))
                lcd_mem = [line1, line2]
                if len(line2.strip()) > 0:
                    x = min(len(line2), 15)
                    lcd.move_to(x, 1)
                elif len(line1.strip()) > 0:
                    x = min(len(line1), 15)
                    lcd.move_to(x, 0)
                    if len(line1) == 16:
                        lcd.move_to(0, 1)
                else:
                    lcd.move_to(0, 0)
                if len(line2) == 16:
                    lcd.hide_cursor()
                else:
                    lcd.blink_cursor_on()
            except Exception as ex:
                print("LCD error:", ex)
        sleep_ms(50)

def on_recv_thread():
    """Thread to listen for incoming ESP-NOW messages and enqueue them."""
    global lcd_queue
    while True:
        host, raw = e.recv()
        if raw:
            try:
                # Messages are expected as b'line1|line2'
                text = raw.decode().split("|", 1)
                if len(text) == 2:
                    line1, line2 = text
                else:
                    line1, line2 = text[0], ""
                with lcd_lock:
                    lcd_queue = []
                    lcd_queue.append((line1, line2))
            except Exception as ex:
                print("Decode error:", ex)

# Start threads
_thread.start_new_thread(lcd_worker, ())
_thread.start_new_thread(on_recv_thread, ())

print("LCD worker ready, waiting for ESP-NOW messages...")
while True:
    sleep_ms(1000)
