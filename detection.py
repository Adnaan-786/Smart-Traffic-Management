"""
Vehicle detection from traffic camera video.

Each VideoFeed owns one video file, decodes it on a background thread, runs
YOLO over the frames, and keeps both the latest annotated JPEG and the current
vehicle count available for the dashboard to read.

Two models run side by side. yolo11n counts ordinary vehicles, one instance
per feed. It is COCO-trained, so it has no ambulance, fire truck or police
class; a second model handles those, shared across the feeds by
EmergencyWatcher because it is far heavier.
"""

import os
import threading
import time

import cv2
import numpy as np

# COCO class ids for the vehicle types worth counting at an intersection.
# Names on the right are COCO's own spellings, which is why "bike" never
# matched anything: COCO calls it "bicycle".
VEHICLE_CLASSES = {
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

MODEL_PATH = "yolo11n.pt"
INFERENCE_SIZE = 640      # Frames are scaled to this before detection
CONFIDENCE = 0.35         # Minimum detection confidence
TARGET_FPS = 8            # Detections per second per feed

# A second model handles emergency vehicles, which COCO cannot represent.
# Set EMERGENCY_MODEL to empty to turn it off, or to another weights file.
EMERGENCY_MODEL_PATH = os.environ.get("EMERGENCY_MODEL", "models/emergency.pt")
EMERGENCY_CLASSES = {0: "Ambulance", 1: "Fire_Truck", 2: "Police"}

# Measured over ~30 frames per clip on six traffic scenes containing emergency
# vehicles and four without: at 0.5 the model fires on 62% of emergency frames
# and 0.8% of ordinary ones. That single stray frame is isolated, so requiring
# two checks in a row before believing it removes false alarms entirely.
EMERGENCY_CONFIDENCE = float(os.environ.get("EMERGENCY_CONF", "0.5"))
EMERGENCY_CONFIRMATIONS = 2
EMERGENCY_INTERVAL = 0.35  # Seconds between checks, cycling through the feeds
EMERGENCY_HOLD = 4.0       # Keep a sighting active this long after it is last seen

# Model loading is serialised, but each feed gets its own model instance.
# Ultralytics keeps per-call state on a shared predictor, so one model driven
# from several threads races on both that state and the one-off fuse step.
_load_lock = threading.Lock()


def load_model():
    """Loads and warms up a YOLO model for the calling thread's exclusive use."""
    with _load_lock:
        from ultralytics import YOLO
        model = YOLO(MODEL_PATH)
        # Run one throwaway frame while still holding the lock. The first
        # predict() fuses the model in place, and two threads fusing at once
        # fail with "'Conv' object has no attribute 'bn'".
        model.predict(np.zeros((64, 64, 3), dtype=np.uint8), verbose=False)
        return model


class VideoFeed:
    """A single traffic camera: decodes a video, detects vehicles, loops forever."""

    def __init__(self, path, name):
        self.path = path
        self.name = name
        self.vehicle_count = 0
        self.class_counts = {}
        self.fps = 0.0
        self.error = None

        # Set by the emergency worker, not by this feed's own thread
        self.emergency = False
        self.emergency_label = None
        self.emergency_conf = 0.0
        self._emergency_seen_at = None
        self._emergency_streak = 0
        self._raw_frame = None

        self._jpeg = None
        self._lock = threading.Lock()
        self._running = False

    def start(self):
        """Begins decoding and detecting on a background thread."""
        if self._running:
            return self
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def _loop(self):
        """Reads frames, runs detection, and stores the annotated result."""
        cap = cv2.VideoCapture(self.path)
        if not cap.isOpened():
            self.error = f"could not open {self.path}"
            self._running = False
            return

        model = load_model()
        frame_interval = 1.0 / TARGET_FPS
        recent = []          # Wall-clock gaps between delivered frames
        last_frame_at = None

        while self._running:
            started = time.time()

            success, frame = cap.read()
            if not success:
                # Loop the clip so the feed runs continuously
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            results = model.predict(
                frame,
                imgsz=INFERENCE_SIZE,
                conf=CONFIDENCE,
                classes=list(VEHICLE_CLASSES),
                verbose=False,
            )[0]

            # Count detections per vehicle class
            counts = {}
            for cls_id in results.boxes.cls.tolist():
                label = VEHICLE_CLASSES.get(int(cls_id))
                if label:
                    counts[label] = counts.get(label, 0) + 1

            annotated = results.plot()
            ok, buffer = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])

            elapsed = time.time() - started

            # Measure the rate frames are actually delivered at, not how fast
            # inference alone runs, so the number on screen means what it says.
            now = time.time()
            if last_frame_at is not None:
                recent.append(now - last_frame_at)
                del recent[:-20]
            last_frame_at = now

            with self._lock:
                self._raw_frame = frame
                self.vehicle_count = sum(counts.values())
                self.class_counts = counts
                self.fps = len(recent) / sum(recent) if sum(recent) else 0.0
                if ok:
                    self._jpeg = buffer.tobytes()

            # Hold the target frame rate rather than decoding as fast as possible
            time.sleep(max(0.0, frame_interval - elapsed))

        cap.release()

    def stop(self):
        """Stops the background thread."""
        self._running = False

    def latest_jpeg(self):
        """Returns the most recent annotated frame as JPEG bytes, or None."""
        with self._lock:
            return self._jpeg

    def latest_frame(self):
        """Returns the most recent undecorated frame, for the emergency worker."""
        with self._lock:
            return self._raw_frame

    def set_emergency(self, label, conf):
        """
        Records an emergency sighting. Called by the emergency worker.

        A sighting is only believed after EMERGENCY_CONFIRMATIONS checks in a
        row, which is what keeps a single stray frame of ordinary traffic from
        raising a false alarm. Clearing waits for the hold time to pass, so a
        vehicle that flickers between frames does not flicker on the dashboard.
        """
        now = time.time()
        with self._lock:
            if label:
                self._emergency_streak += 1
                if self._emergency_streak >= EMERGENCY_CONFIRMATIONS:
                    self.emergency = True
                    self.emergency_label = label
                    self.emergency_conf = conf
                    self._emergency_seen_at = now
            else:
                self._emergency_streak = 0
                if self._emergency_seen_at and now - self._emergency_seen_at > EMERGENCY_HOLD:
                    self.emergency = False
                    self.emergency_label = None
                    self.emergency_conf = 0.0
                    self._emergency_seen_at = None

    def snapshot(self):
        """Returns the current detection numbers for this feed."""
        with self._lock:
            return {
                "name": self.name,
                "vehicle_count": self.vehicle_count,
                "class_counts": dict(self.class_counts),
                "fps": round(self.fps, 1),
                "error": self.error,
                "emergency": self.emergency,
                "emergency_label": self.emergency_label,
                "emergency_conf": round(self.emergency_conf, 2),
            }


class EmergencyWatcher:
    """
    Watches every feed for emergency vehicles using a single shared model.

    The emergency model is roughly ten times heavier than the vehicle counter,
    so one worker cycles through the feeds rather than each feed running its
    own copy. On Apple silicon it runs on the GPU, which is about twelve times
    faster than CPU and makes the whole thing practical.
    """

    def __init__(self, feeds):
        self.feeds = feeds
        self.device = None
        self.error = None
        self.latency_ms = 0.0
        self._running = False

    @staticmethod
    def pick_device():
        """Returns the fastest device available for the emergency model."""
        try:
            import torch
            if torch.backends.mps.is_available():
                return "mps"
            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
        return "cpu"

    def start(self):
        """Begins watching on a background thread."""
        if self._running:
            return self
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def stop(self):
        self._running = False

    def _loop(self):
        try:
            from ultralytics import YOLO
            model = YOLO(EMERGENCY_MODEL_PATH)
            self.device = self.pick_device()
            model.predict(np.zeros((64, 64, 3), dtype=np.uint8),
                          device=self.device, verbose=False)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self._running = False
            return

        index = 0
        while self._running:
            started = time.time()
            feed = self.feeds[index % len(self.feeds)]
            index += 1

            frame = feed.latest_frame()
            if frame is None:
                time.sleep(EMERGENCY_INTERVAL)
                continue

            try:
                result = model.predict(
                    frame,
                    imgsz=INFERENCE_SIZE,
                    conf=EMERGENCY_CONFIDENCE,
                    classes=list(EMERGENCY_CLASSES),
                    device=self.device,
                    verbose=False,
                )[0]
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                time.sleep(1.0)
                continue

            # Keep the most confident sighting in this frame
            best, best_conf = None, 0.0
            for cls_id, conf in zip(result.boxes.cls.tolist(), result.boxes.conf.tolist()):
                if conf > best_conf:
                    best, best_conf = EMERGENCY_CLASSES.get(int(cls_id)), conf
            feed.set_emergency(best, best_conf)

            self.latency_ms = (time.time() - started) * 1000
            time.sleep(max(0.0, EMERGENCY_INTERVAL - (time.time() - started)))

    def status(self):
        """Returns how the watcher is running, for the dashboard."""
        return {
            "device": self.device,
            "latency_ms": round(self.latency_ms),
            "error": self.error,
        }
