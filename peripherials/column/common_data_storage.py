import ujson


class DataStorage:
    """
    Shared data store passed between async tasks.

    Acts as a lightweight message-bus on MicroPython's cooperative scheduler.
    Because only one coroutine runs at a time, no locking is needed.

    Data flows
    ──────────
      MotionSensor  →  update_distance()       →  LED task, BLE task
      BLE task      →  queue_led_config()      →  LED task (applied next loop)
    """

    # Keys accepted in a config payload and the LED setter they map to.
    # The LED task iterates this to apply pending config safely off the IRQ.
    CONFIG_KEY_MAP = {
        "min_b": "set_min_brightness",
        "max_b": "set_max_brightness",
        "min_d": "set_min_distance_expected",
        "max_d": "set_max_distance_expected",
    }

    def __init__(self) -> None:
        self.distance_to_person: int = 0
        self.sensor_failing_state: bool = False

        # Pending LED configuration received over BLE.
        # Written by the BLE IRQ handler (via queue_led_config),
        # consumed and cleared by the LED task (via pop_led_config).
        # Storing a dict rather than calling LED setters directly keeps
        # the IRQ handler fast and avoids any re-entrancy issues.
        self._pending_led_config: dict | None = None

    # ───────────────────────── Sensor ─────────────────────────

    def update_distance(self, new_distance: int) -> None:
        """Store the latest distance reading (cm)."""
        self.distance_to_person = new_distance

    def set_sensor_failing_state(self, failing: bool) -> None:
        """Mark whether the sensor is currently in a failure state."""
        self.sensor_failing_state = failing

    # ───────────────────────── LED config (BLE → LED task) ─────────────────────────

    def queue_led_config(self, raw_bytes: bytes) -> None:
        """
        Parse a JSON config payload received over BLE and store it for the
        LED task to apply on its next iteration.

        Expected JSON keys (all optional):
            min_b  – minimum brightness  (0–255)
            max_b  – maximum brightness  (0–255)
            min_d  – minimum distance cm (maps to max brightness)
            max_d  – maximum distance cm (maps to min brightness)

        Example payload: b'{"min_b":10,"max_b":200,"min_d":30,"max_d":300}'

        Invalid JSON is silently dropped so a malformed BLE write can never
        crash the firmware.
        """
        try:
            config = ujson.loads(raw_bytes.decode("utf-8"))
            if isinstance(config, dict):
                self._pending_led_config = config
        except Exception as e:
            print("[DataStorage] Bad config payload, ignored:", e)

    def pop_led_config(self) -> dict | None:
        """
        Return and clear any pending LED config dict, or None if none is waiting.
        Called by the LED task at the top of its loop.
        """
        cfg = self._pending_led_config
        self._pending_led_config = None
        return cfg
