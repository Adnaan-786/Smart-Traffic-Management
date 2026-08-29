"""
Web dashboard for the smart traffic management system.

Runs the traffic controller on a background thread and serves a live view of
the intersection, including the annotated camera feeds it is analysing.

Start locally with:  python3 app.py
Set FEEDS=0 to run the built-in density simulation instead of the videos.
"""

import os
import time

from flask import Flask, Response, jsonify, render_template

import simulation

app = Flask(__name__)
# Pick up template edits without a restart while developing locally
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Camera feeds are on by default. They need ultralytics and PyTorch installed,
# so FEEDS=0 falls back to the simulation for a lightweight run.
USE_VIDEO = os.environ.get("FEEDS", "1") != "0"

# One controller per process, started as soon as the app is imported so the
# simulation is already running by the time the first request arrives.
controller = simulation.TrafficController(use_video=USE_VIDEO).start_background()

STREAM_FPS = 8


@app.route("/")
def index():
    """Serves the dashboard page."""
    return render_template("index.html")


@app.route("/api/state")
def state():
    """Returns the current intersection state as JSON for the dashboard to poll."""
    return jsonify(controller.get_state())


@app.route("/feed/<int:index>")
def feed(index):
    """Streams one camera's annotated frames as MJPEG."""
    if index >= len(controller.feeds):
        return "no such feed", 404

    camera = controller.feeds[index]

    def frames():
        interval = 1.0 / STREAM_FPS
        while True:
            jpeg = camera.latest_jpeg()
            if jpeg:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            time.sleep(interval)

    return Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/healthz")
def healthz():
    """Simple health check for the hosting platform."""
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # threaded so the MJPEG streams don't block the state polling
    app.run(host="0.0.0.0", port=port, threaded=True)
