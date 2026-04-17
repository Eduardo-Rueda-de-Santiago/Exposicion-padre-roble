class DataStorage:
    """
    Shared data store passed between async tasks.

    Acts as a lightweight message-bus: the sensor writes to it,
    the LED controller and any future consumers read from it.
    """

    def __init__(self) -> None:
        self.distance_to_person: int = 0
        self.sensor_failing_state: bool = False

    def update_distance(self, new_distance: int) -> None:
        """Store the latest distance reading (cm)."""
        self.distance_to_person = new_distance

    def set_sensor_failing_state(self, failing: bool) -> None:
        """Mark whether the sensor is currently in a failure state."""
        self.sensor_failing_state = failing
