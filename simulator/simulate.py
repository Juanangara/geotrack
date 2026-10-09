"""Simulates couriers moving around Bogota and sends their positions to the API."""
import argparse
import asyncio
import math
import random

import httpx

METERS_PER_DEGREE_LAT = 111_320

# Bounding box over Bogota: (min_lat, max_lat, min_lon, max_lon)
BBOX = (4.55, 4.78, -74.15, -74.02)


class SimulatedCourier:
    def __init__(self, courier_id: int, speed_mps: float):
        self.id = courier_id
        self.speed = speed_mps
        self.lat = random.uniform(BBOX[0], BBOX[1])
        self.lon = random.uniform(BBOX[2], BBOX[3])
        self.heading = random.uniform(0, 360)  # degrees, 0 = north

    def step(self, seconds: float) -> None:
        # Small random turn so the path looks natural
        self.heading = (self.heading + random.uniform(-25, 25)) % 360
        distance = self.speed * seconds
        rad = math.radians(self.heading)
        self.lat += distance * math.cos(rad) / METERS_PER_DEGREE_LAT
        self.lon += distance * math.sin(rad) / (
            METERS_PER_DEGREE_LAT * math.cos(math.radians(self.lat))
        )
        # Bounce back when leaving the bounding box
        if not BBOX[0] <= self.lat <= BBOX[1] or not BBOX[2] <= self.lon <= BBOX[3]:
            self.heading = (self.heading + 180) % 360
            self.lat = min(max(self.lat, BBOX[0]), BBOX[1])
            self.lon = min(max(self.lon, BBOX[2]), BBOX[3])


async def run_courier(client: httpx.AsyncClient, courier: SimulatedCourier,
                      interval: float, ticks: int | None) -> None:
    sent = 0
    while ticks is None or sent < ticks:
        courier.step(interval)
        resp = await client.post(
            "/positions",
            json={"courier_id": courier.id, "lat": courier.lat, "lon": courier.lon},
        )
        if resp.status_code != 201:
            print(f"courier {courier.id}: API returned {resp.status_code} {resp.text}")
        else:
            print(f"courier {courier.id}: {courier.lat:.5f}, {courier.lon:.5f}")
        sent += 1
        await asyncio.sleep(interval)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--couriers", default="1,2,3", help="comma-separated courier ids")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between pings")
    parser.add_argument("--speed", type=float, default=8.0, help="meters per second")
    parser.add_argument("--ticks", type=int, default=None, help="pings per courier (default: forever)")
    args = parser.parse_args()

    couriers = [SimulatedCourier(int(i), args.speed) for i in args.couriers.split(",")]
    async with httpx.AsyncClient(base_url=args.api) as client:
        await asyncio.gather(
            *(run_courier(client, c, args.interval, args.ticks) for c in couriers)
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("stopped")
