from operator import ne


class DataStorage:
    def __init__(self) -> None:
        self.distance_to_person: int = 500
        self.sensor_failing_state: bool = False

    def update_distance(self, new_distance: int):
        self.distance_to_person = new_distance

    def set_sensor_failing_state(self, new_sensor_failing_state: bool):
        self.sensor_failing_state = new_sensor_failing_state
