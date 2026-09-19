import logging
import time

import board
from adafruit_pn532.i2c import PN532_I2C

logger = logging.getLogger(__name__)


class NfcReader:
    def __init__(
        self,
        i2c_bus: int,
        i2c_address: int,
        poll_interval: float,
        debounce_seconds: float,
    ) -> None:
        self._poll_interval = poll_interval
        self._debounce_seconds = debounce_seconds
        self._i2c_address = i2c_address

        self._reported_uid: str | None = None
        self._last_report_time: float | None = None
        self._last_seen_time: float | None = None
        self._tag_present = False

        logger.info(
            "Initializing PN532: bus=%d address=0x%02X poll=%.2fs debounce=%.1fs",
            i2c_bus,
            i2c_address,
            poll_interval,
            debounce_seconds,
        )

        i2c = board.I2C()
        self._reader = PN532_I2C(i2c, address=i2c_address)
        self._reader.SAM_configuration()

        fw = self._reader.firmware_version
        logger.info("PN532 firmware version: %s", fw)

    def poll(self) -> str | None:
        uid_bytes = self._reader.read_passive_target(timeout=self._poll_interval)
        now = time.monotonic()

        if uid_bytes is not None:
            uid = ":".join(f"{b:02X}" for b in uid_bytes)
            self._tag_present = True
            self._last_seen_time = now

            if uid == self._reported_uid:
                return None

            if (
                self._last_report_time is not None
                and (now - self._last_report_time) < self._debounce_seconds
            ):
                return None

            self._reported_uid = uid
            self._last_report_time = now
            logger.info("Tag detected: %s", uid)
            return uid
        else:
            self._tag_present = False
            self._reported_uid = None
            return None

    def is_tag_present(self) -> bool:
        return self._tag_present

    def cleanup(self) -> None:
        logger.info("NFC reader cleanup")
