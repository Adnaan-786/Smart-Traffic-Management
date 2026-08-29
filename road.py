import database
import numpy as np
import time

# Shortest green a road can get, so a road with almost nothing on it still
# holds the light long enough for waiting vehicles to actually move.
MIN_GREEN_TIME = 5

class Road:
    def __init__(self, name, vehicle_count, capacity, total_time, rate_of_increase, file_path=None):
        """
        Initializes a new Road instance with the specified attributes.
        Calculates initial green light time based on vehicle count and capacity.
        """
        self.next = Road  # Placeholder for linking roads in a network
        # Calculate initial green time based on current vehicle count and capacity
        green_time = vehicle_count / capacity * total_time
        # Add road data to database and store the assigned road id
        self.id = database.add_road(name, green_time, vehicle_count, capacity, total_time, False, file_path)
        self.rate_of_increase = rate_of_increase  # Rate at which vehicle count increases when red
        self.is_green = False  # Current traffic light state
        self.emergency_triggered_at = None  # Timestamp for emergency vehicle trigger
        self._fractional_vehicles = 0.0  # Carries sub-vehicle changes between updates

    def get_vehicle_count(self):
        """Returns the current vehicle count from the database."""
        return database.get_vehicle_count(self.id)

    def get_name(self):
        """Returns the name of the road."""
        return database.get_name(self.id)

    def get_green_time(self):
        """Returns the current green light duration for this road."""
        return database.get_green_time(self.id)

    def get_hasEmergencyVehicle(self):
        """Returns whether an emergency vehicle is currently detected on this road."""
        return database.get_hasEmergencyVehicle(self.id)

    def turn_red(self):
        """Sets the traffic light state to red."""
        self.is_green = False

    def turn_green(self):
        """Sets the traffic light state to green."""
        self.is_green = True

    def update(self):
        """
        Updates the road using the built-in density simulation: vehicles arrive
        while the light is red and clear while it is green.
        """
        vehicle_count = database.get_vehicle_count(self.id)
        capacity = database.get_capacity(self.id)
        total_time = database.get_total_time(self.id)

        # Adjust vehicle count based on traffic light state
        if self.is_green:
            # Clear vehicles at the rate the green time formula already assumes:
            # a queue at full capacity takes exactly total_time seconds to drain.
            change = -capacity / total_time * (1 + np.random.uniform(-0.1, 0.1))  # Randomized clearance rate
        else:
            # Increase vehicle count if the light is red, simulating vehicle arrival
            change = self.rate_of_increase * (1 + np.random.uniform(-0.2, 0.2))  # Randomized increase rate

        # Carry the leftover fraction into the next update rather than truncating
        # it away, which used to round every clearance down to zero vehicles.
        self._fractional_vehicles += change
        whole_vehicles = int(self._fractional_vehicles)
        self._fractional_vehicles -= whole_vehicles

        # A queue cannot go negative or exceed what the road can hold
        vehicle_count = max(0, min(vehicle_count + whole_vehicles, capacity))

        self._store_count(vehicle_count, capacity, total_time)
        self._update_emergency()

    def cam_update(self, detected_count):
        """
        Updates the road from a camera reading instead of the density
        simulation. The vehicle count becomes what YOLO saw in that frame.
        """
        capacity = database.get_capacity(self.id)
        total_time = database.get_total_time(self.id)

        vehicle_count = max(0, min(detected_count, capacity))

        self._store_count(vehicle_count, capacity, total_time)
        self._update_emergency()

    def _store_count(self, vehicle_count, capacity, total_time):
        """Persists the vehicle count and the green time implied by it."""
        database.update_vehicle_count(self.id, vehicle_count)
        green_time = max(MIN_GREEN_TIME, vehicle_count / capacity * total_time)
        database.update_green_time(self.id, green_time)

    def _update_emergency(self):
        """
        Randomly triggers an emergency vehicle and clears it after a few seconds.

        This stays simulated because the bundled COCO model has no ambulance,
        fire truck or police class, so emergency vehicles cannot be recognised
        from the video feeds.
        """
        # Trigger emergency vehicle randomly with a low probability and only if no emergency is active
        if np.random.rand() < 0.005 and self.emergency_triggered_at is None:  # 0.5% chance
            database.update_hasEmergencyVehicle(self.id, True)
            self.emergency_triggered_at = time.time()  # Record emergency trigger time

        # Check if the emergency vehicle duration has passed and reset if necessary
        if self.emergency_triggered_at:
            elapsed_time = time.time() - self.emergency_triggered_at
            if elapsed_time > 5:  # Clear emergency status after 5 seconds
                database.update_hasEmergencyVehicle(self.id, False)
                self.emergency_triggered_at = None  # Reset emergency trigger
