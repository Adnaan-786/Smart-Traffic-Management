"""
Traffic controller engine shared by the console runner (main.py) and the
web dashboard (app.py).

The controller owns the road cycle; callers drive it either by looping over
step() themselves or by calling start_background() and reading get_state().
"""

import threading
import time

import database
from road import Road

# Roads are recreated on every process start, so the simulation always begins
# from a known state rather than inheriting rows from a previous run.
ROAD_SETTINGS = [
    # name,     vehicle_count, capacity, total_time, rate_of_increase
    ("Road 1", 40, 1000, 300, 1),
    ("Road 2", 60, 800, 300, 2),
    ("Road 3", 70, 1100, 300, 1.7),
    ("Road 4", 30, 700, 300, 1.2),
]

# Camera feed per road, used when the controller runs with use_video=True.
# Capacities are far larger than any single camera frame can show, so in video
# mode they are scaled down to the range a real detection can actually reach.
FEED_PATHS = ["feeds/road-1.mp4", "feeds/road-2.mp4", "feeds/road-3.mp4", "feeds/road-4.mp4"]
VIDEO_CAPACITY = 25    # Roughly the most vehicles one camera frame can hold
VIDEO_TOTAL_TIME = 45  # A full frame of traffic earns a 45s green, not 300s

MAX_EVENTS = 40  # Number of recent events kept for the dashboard feed


class TrafficController:
    """Cycles green lights across a ring of roads, pre-empting for emergencies."""

    def __init__(self, use_video=False):
        database.create_database()

        self.use_video = use_video
        self.roads = [Road(*settings) for settings in ROAD_SETTINGS]

        # In video mode the vehicle count is whatever the camera sees, which is
        # a handful of vehicles rather than a road-sized queue. Rescale capacity
        # so green times stay in a sensible range.
        if use_video:
            for road in self.roads:
                database.update_capacity(road.id, VIDEO_CAPACITY)
                database.update_total_time(road.id, VIDEO_TOTAL_TIME)

        self.feeds = []
        if use_video:
            import detection
            self.feeds = [
                detection.VideoFeed(path, settings[0]).start()
                for path, settings in zip(FEED_PATHS, ROAD_SETTINGS)
            ]
        # Link the roads into a ring so each one knows its successor
        for current, following in zip(self.roads, self.roads[1:] + self.roads[:1]):
            current.next = following

        self.active_road = self.roads[0]
        self.active_road.turn_green()
        self.start_time = time.time()
        self.road_timestamp = self.start_time

        self.events = []
        self._prev_emergency = {road.id: False for road in self.roads}
        self._feed_snapshots = [feed.snapshot() for feed in self.feeds]
        self._lock = threading.Lock()
        self._snapshot = {}
        self._refresh_snapshot()

    def _record(self, message):
        """Adds a timestamped event to the feed, trimming the oldest entries."""
        self.events.append({"time": time.strftime("%H:%M:%S"), "message": message})
        del self.events[:-MAX_EVENTS]
        return message

    def _switch_to(self, road, curr_time):
        """Moves the green light to the given road."""
        self.active_road.turn_red()
        self.active_road = road
        self.active_road.turn_green()
        self.start_time = curr_time

    def step(self):
        """
        Advances the simulation by one iteration.
        Returns the list of event messages produced by this step.
        """
        curr_time = time.time()
        new_events = []

        # Hand the green light to the next road once this road's time is up
        if curr_time - self.start_time > self.active_road.get_green_time():
            following = self.active_road.next
            new_events.append(self._record(
                f"Switching green light from {self.active_road.get_name()} to {following.get_name()}"
            ))
            self._switch_to(following, curr_time)

        # Report emergencies as they appear and clear
        emergencies = {road.id: bool(road.get_hasEmergencyVehicle()) for road in self.roads}
        for road in self.roads:
            if emergencies[road.id] != self._prev_emergency[road.id]:
                verb = "detected on" if emergencies[road.id] else "cleared from"
                new_events.append(self._record(f"Emergency vehicle {verb} {road.get_name()}"))
                self._prev_emergency[road.id] = emergencies[road.id]

        # An emergency vehicle takes priority over the normal cycle
        for road in self.roads:
            if emergencies[road.id]:
                # Only act if this road isn't already the one holding green
                if self.active_road != road:
                    new_events.append(self._record(
                        f"Prioritizing {road.get_name()} for emergency vehicle"
                    ))
                    self._switch_to(road, curr_time)
                break

        # Recalculate densities and green times once a second
        if curr_time - self.road_timestamp > 1:
            for index, road in enumerate(self.roads):
                if self.feeds:
                    # One reading per road per tick, reused for both the signal
                    # decision and the dashboard, so the two never disagree.
                    reading = self.feeds[index].snapshot()
                    self._feed_snapshots[index] = reading
                    road.cam_update(reading["vehicle_count"])
                else:
                    road.update()
            self.road_timestamp = curr_time

        self._refresh_snapshot()
        return new_events

    def _refresh_snapshot(self):
        """Stores a plain-dict view of the current state for other threads to read."""
        feeds = self._feed_snapshots
        state = {
            "active_road": self.active_road.get_name(),
            "elapsed": round(time.time() - self.start_time, 1),
            "green_time": round(self.active_road.get_green_time() or 0, 1),
            "use_video": self.use_video,
            "roads": [
                {
                    "name": road.get_name(),
                    "vehicle_count": road.get_vehicle_count(),
                    "capacity": database.get_capacity(road.id),
                    "green_time": round(road.get_green_time() or 0, 1),
                    "is_green": road.is_green,
                    "emergency": bool(road.get_hasEmergencyVehicle()),
                    "feed": feeds[index] if index < len(feeds) else None,
                }
                for index, road in enumerate(self.roads)
            ],
            "events": list(reversed(self.events)),
        }
        with self._lock:
            self._snapshot = state

    def get_state(self):
        """Returns the most recent state snapshot. Safe to call from any thread."""
        with self._lock:
            return self._snapshot

    def run_forever(self, on_event=None):
        """Runs the control loop until interrupted, reporting events to on_event."""
        while True:
            for message in self.step():
                if on_event:
                    on_event(message)
            # Brief pause so the loop doesn't spin the CPU at full speed
            time.sleep(0.05)

    def start_background(self):
        """Runs the control loop on a daemon thread and returns the controller."""
        thread = threading.Thread(target=self.run_forever, daemon=True)
        thread.start()
        return self
