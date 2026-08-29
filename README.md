
# Smart Traffic Management System with Emergency Vehicle Prioritization

**Tagline:** Efficient and Intelligent Traffic Control to Prioritize Emergency Vehicles and Reduce Congestion.

## 1. Project Description

### Overview
This project is a smart traffic management system designed to optimize traffic light cycles based on real-time data, with special prioritization for emergency vehicles. By dynamically adjusting green-light timings, it aims to reduce congestion and enable emergency vehicles to navigate intersections more efficiently.

### Problem Statement
Urban areas face significant traffic congestion, often resulting in delays for emergency vehicles at intersections. This project addresses this problem by automatically adjusting traffic lights to prioritize emergency vehicles and manage vehicle density more effectively.

## 2. Features

- **Real-Time Traffic Control:** Dynamically adjusts traffic light timings based on real-time vehicle density at each intersection.
- **Emergency Vehicle Prioritization:** Grants a road with an emergency vehicle an immediate green signal, pre-empting the normal cycle. The detection itself is simulated; see [Emergency vehicles are simulated](#emergency-vehicles-are-simulated).
- **Adaptive Timing Mechanism:** Uses the vehicle count and rate of increase on each road to calculate optimized green-light durations.
- **Data Persistence with SQLite:** Efficiently stores and retrieves road traffic data for analysis of ongoing traffic patterns.

## 3. Tech Stack

- **Programming Language:** Python
- **Web Framework:** Flask, serving a live dashboard of the intersection
- **Database:** SQLite for efficient data storage and retrieval
- **Libraries:**
  - `ultralytics` for computer vision applications
  - `sqlite3` for database interactions
  - `numpy` for statistical adjustments in vehicle density calculations
  - Additional libraries like `time` for managing timing intervals

## Running It

The dashboard shows the four camera feeds with YOLO detections drawn on them,
and drives the signal timing from what it detects.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-detection.txt
.venv/bin/python app.py
```

Then open http://localhost:5000. Set `PORT` to use a different port.

The detection dependencies are large (PyTorch is roughly 1GB). To run without
them, install only `requirements.txt` and set `FEEDS=0`, which falls back to
the built-in density simulation and shows the cards without video:

```bash
FEEDS=0 python3 app.py
```

**Console runner** — the same controller printing a status block each second:

```bash
python3 -u main.py
```

The `-u` matters: without it Python buffers the output and the terminal looks
frozen. `FEEDS=1` drives it from the cameras instead of the simulation.

## How the detection works

Each road has a camera feed in `feeds/`, listed in `feeds/CREDITS.md`. For
every feed, `detection.py` runs a background thread that decodes frames, runs
`yolo11n` over them at 8 fps, and keeps both the annotated JPEG and the current
vehicle count. The dashboard streams the annotated frames as MJPEG from
`/feed/<n>` and reads the counts from `/api/state`.

Detected vehicles are the COCO classes `bicycle`, `car`, `motorcycle`, `bus`
and `truck`. A road's green time is recalculated once a second from the count
its camera currently sees, so a busier approach earns a longer green.

Each feed gets its own model instance. Ultralytics keeps per-call state on a
shared predictor and fuses the model in place on first use, so driving one
model from several threads crashes.

## Intersection simulation

Below the camera feeds the dashboard draws a top-down view of the junction, in
the spirit of [A/B Street](https://github.com/a-b-street/abstreet). Recorded
footage cannot react to our signals, so the feeds alone show the counts
changing but never show the control doing anything. The simulation closes that
loop: queue length on each approach tracks that camera's detected count,
vehicles hold at the stop line while their signal is red, and pull away once it
turns green. When a road is prioritised for an emergency, its lead vehicle is
highlighted and gets waved through ahead of the cycle.

The server stays the authority. It decides which road holds green and reports
what each camera detects; the canvas only draws the consequences. Vehicle
motion is a car-following model in the browser, so the animation stays smooth
without adding server load.

### Emergency vehicles are simulated

The bundled `yolo11n.pt` is COCO-trained, and COCO has no ambulance, fire
truck or police class, so emergency vehicles cannot be recognised from these
feeds. The original code searched for `"cops"`, `"ambulance"` and
`"fire truck"`, none of which the model can ever return. Emergency events
therefore stay on the original random trigger and are labelled as simulated
in the dashboard. Genuine detection would need a model trained on those
classes.

## Deploying to Render

The repository includes a `render.yaml` blueprint, so Render configures the
service automatically:

1. Push this repository to GitHub.
2. In the Render dashboard, choose **New > Web Service** and select the repo.
3. Render reads `render.yaml` and fills in the build and start commands.
4. Deploy.

A deployed instance runs with `FEEDS=0` and shows no video. Camera detection
needs PyTorch, which does not fit in the free tier's 512MB, so the feeds are a
local-only feature.

Two things to know about the free tier: the service **spins down after about
15 minutes of inactivity**, so the simulation restarts on the next visit, and
the filesystem is **ephemeral**, so `road.db` is rebuilt on every deploy. Both
are harmless here, since the database is recreated automatically at startup.

The service must run with a **single worker**. Each additional worker would
start its own copy of the simulation, and requests would then see whichever
one happened to answer.

### Known limitation: demand exceeds capacity

Green lights clear queues correctly, but the configured demand is more than
the intersection can serve. A road's queue is stable when what arrives on red
equals what clears on green, which means it needs a green fraction of
`rate_of_increase / (rate_of_increase + capacity / total_time)`:

| Road | Arrivals/s | Clears/s | Green needed |
|------|-----------|----------|--------------|
| Road 1 | 1.0 | 3.33 | 23.1% |
| Road 2 | 2.0 | 2.67 | 42.9% |
| Road 3 | 1.7 | 3.67 | 31.7% |
| Road 4 | 1.2 | 2.33 | 34.0% |
| | | | **131.6%** |

Those fractions sum to more than one cycle, so demand exceeds capacity by
roughly 24% and no signal timing can hold the queues steady. Individual roads
drain visibly on green, but the totals drift upward over tens of minutes until
they reach the capacity clamp.

This is a property of the road parameters, not of the control logic. Lowering
`rate_of_increase` in `simulation.py` until the green fractions sum to under
100% makes the intersection stable indefinitely.

## 4. How It Works

### Database Schema
The database includes a table for each road, containing fields like:
- **`green_time`** - Duration of green light in seconds
- **`vehicle_count`** - Current count of vehicles in the road region
- **`capacity`** - Total capacity of vehicles the road can hold

### Road and Traffic Management Logic
- **Road Class:** Models each road's behavior, tracks traffic data, and handles updates.
- **Process Loop:** Monitors vehicle counts, calculates optimized green times, and switches active roads to ensure optimal traffic flow.
  
### Emergency Vehicle Handling
The controller continuously checks each road for an emergency vehicle. When one
appears, the light state updates immediately to give that road green, cutting
the current phase short.

The presence flag itself is simulated rather than detected: the bundled
COCO-trained model has no ambulance, fire truck or police class. See
[Emergency vehicles are simulated](#emergency-vehicles-are-simulated).

## 5. Challenges and Solutions

- **Dynamic Traffic Data Management:** Efficiently handling and storing dynamic traffic data presented a challenge. Implementing SQLite provided a lightweight solution, balancing functionality with performance for real-time updates.
  
## 6. Future Improvements

- **Machine Learning for Traffic Prediction:** Integrate machine learning models to forecast traffic patterns based on historical data.
- **Real-Time Camera Integration:** Add direct camera data processing for enhanced vehicle counting accuracy.
- **Multi-Intersection Traffic Management:** Scale the system to handle a network of intersections for comprehensive traffic optimization.
