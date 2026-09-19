import time
import board
from adafruit_pn532.i2c import PN532_I2C

I2C_ADDRESSES = [0x24, 0x48]
DEBOUNCE_SECONDS = 1.0
POLL_TIMEOUT = 0.5


import board
import busio
from digitalio import DigitalInOut
from adafruit_pn532.spi import PN532_SPI

def connect():
    spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
    cs_pin = DigitalInOut(board.D8)  # This is your SS pin (GPIO 8)
    reader = PN532_SPI(spi, cs_pin, debug=False)
    reader.SAM_configuration()
    fw = reader.firmware_version
    print(f"PN532 found via SPI")
    print(f"Firmware version: {fw}")
    return reader

def main():
    print("PN532 NFC Reader Test")
    print("=" * 40)
    reader = connect()
    print("\nTap a card on the reader...")
    print("Press Ctrl+C to quit\n")

    last_uid = None
    while True:
        uid = reader.read_passive_target(timeout=POLL_TIMEOUT)
        if uid is not None:
            uid_hex = ":".join(f"{b:02X}" for b in uid)
            if uid_hex != last_uid:
                print(f"UID: {uid_hex}  ({len(uid)} bytes)")
                last_uid = uid_hex
            time.sleep(DEBOUNCE_SECONDS)
        else:
            last_uid = None


if __name__ == "__main__":
    main()
