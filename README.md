
# Smart Traffic Management System with Emergency Vehicle Prioritization

**Tagline:** Efficient and Intelligent Traffic Control to Prioritize Emergency Vehicles and Reduce Congestion.

## 1. Project Description

### Overview
This project is a smart traffic management system designed to optimize traffic light cycles based on real-time data, with special prioritization for emergency vehicles. By dynamically adjusting green-light timings, it aims to reduce congestion and enable emergency vehicles to navigate intersections more efficiently.

### Problem Statement
Urban areas face significant traffic congestion, often resulting in delays for emergency vehicles at intersections. This project addresses this problem by automatically adjusting traffic lights to prioritize emergency vehicles and manage vehicle density more effectively.

## 2. Features

- **Real-Time Traffic Control:** Dynamically adjusts traffic light timings based on real-time vehicle density at each intersection.
- **Emergency Vehicle Detection and Prioritization:** Detects emergency vehicles on the road and grants them a green signal to pass through without delay.
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

Install the runtime dependencies:

```bash
pip install -r requirements.txt
```

**Web dashboard** — a live view of all four roads, the active green light,
and an event feed:

```bash
python3 app.py
```

Then open http://localhost:5000. Set `PORT` to use a different port.

**Console runner** — the same simulation printing a status block each second:

```bash
python3 -u main.py
```

The `-u` matters: without it Python buffers the output and the terminal
looks frozen.

### Camera detection (optional)

`detection.py` uses YOLO to count vehicles from video and is not needed for
the simulation. It is imported lazily, so the project runs without it. To
enable it, install the extra dependencies and call `Road.cam_update()`:

```bash
pip install -r requirements-detection.txt
```

## Deploying to Render

The repository includes a `render.yaml` blueprint, so Render configures the
service automatically:

1. Push this repository to GitHub.
2. In the Render dashboard, choose **New > Web Service** and select the repo.
3. Render reads `render.yaml` and fills in the build and start commands.
4. Deploy.

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
The system continuously checks for emergency vehicles using YOLO-based detection. When an emergency vehicle is detected, the traffic light state updates to provide immediate green light access to that vehicle.

## 5. Challenges and Solutions

- **Dynamic Traffic Data Management:** Efficiently handling and storing dynamic traffic data presented a challenge. Implementing SQLite provided a lightweight solution, balancing functionality with performance for real-time updates.
  
## 6. Future Improvements

- **Machine Learning for Traffic Prediction:** Integrate machine learning models to forecast traffic patterns based on historical data.
- **Real-Time Camera Integration:** Add direct camera data processing for enhanced vehicle counting accuracy.
- **Multi-Intersection Traffic Management:** Scale the system to handle a network of intersections for comprehensive traffic optimization.
