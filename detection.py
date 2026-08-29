"""
Vehicle detection from traffic camera video.

Each VideoFeed owns one video file, decodes it on a background thread, runs
YOLO over the frames, and keeps both the latest annotated JPEG and the current
vehicle count available for the dashboard to read.

The bundled yolo11n.pt is trained on COCO, which has no ambulance, fire truck
or police class, so emergency vehicles cannot be detected from video with this
model. Emergency events stay simulated; see Road.update().
"""

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

    def snapshot(self):
        """Returns the current detection numbers for this feed."""
        with self._lock:
            return {
                "name": self.name,
                "vehicle_count": self.vehicle_count,
                "class_counts": dict(self.class_counts),
                "fps": round(self.fps, 1),
                "error": self.error,
            }
