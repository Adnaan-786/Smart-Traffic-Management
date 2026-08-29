"""
Console runner for the traffic controller.

Prints a status block every second showing vehicle counts and light states.
For the web dashboard, run app.py instead.
"""

import time

import simulation

controller = simulation.TrafficController()
status_timestamp = time.time()

try:
    while True:
        # Advance the simulation and report anything that happened
        for message in controller.step():
            print(message)

        curr_time = time.time()

        # Print a full status block once a second
        if curr_time - status_timestamp > 1:
            state = controller.get_state()

            print("\nUpdating vehicle counts:")
            for road in state["roads"]:
                print(f"Road {road['name']} - Vehicle count: {road['vehicle_count']}")

            print(f"Active road: {state['active_road']}")
            print(f"Time since last switch: {state['elapsed']:.2f} seconds")
            print("Road statuses:")
            for road in state["roads"]:
                print(f"  {road['name']} - Green: {road['is_green']}, Emergency: {road['emergency']}")

            print("\n----------------------------------------------")
            status_timestamp = curr_time

        # Brief pause so the loop doesn't spin the CPU at full speed
        time.sleep(0.05)

except KeyboardInterrupt:
    print("\nStopped.")
