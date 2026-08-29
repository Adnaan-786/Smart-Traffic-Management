"""
Web dashboard for the smart traffic management system.

Runs the traffic controller on a background thread and serves a live view of
the intersection. Start locally with:  python3 app.py
"""

import os

from flask import Flask, jsonify, render_template

import simulation

app = Flask(__name__)

# One controller per process, started as soon as the app is imported so the
# simulation is already running by the time the first request arrives.
controller = simulation.TrafficController().start_background()


@app.route("/")
def index():
    """Serves the dashboard page."""
    return render_template("index.html")


@app.route("/api/state")
def state():
    """Returns the current intersection state as JSON for the dashboard to poll."""
    return jsonify(controller.get_state())


@app.route("/healthz")
def healthz():
    """Simple health check for the hosting platform."""
    return {"status": "ok"}


if __name__ == "__main__":
    # Render supplies the port to bind to via $PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
