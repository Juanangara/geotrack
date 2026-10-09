# geotrack

Live location tracking (delivery style) with PostGIS: geospatial events, proximity queries and a live map.

## Requirements
- Docker

## Run the database
```
cp .env.example .env
docker compose up -d
```

The database listens on port 5434 (set in `.env`).

## Check PostGIS
```
docker compose exec db psql -U geotrack -d geotrack -c "SELECT PostGIS_Version();"
```

## Database schema
Tables are created automatically from `db/*.sql` the first time the database starts:
- `couriers`: delivery people and their status.
- `orders`: delivery destinations (`GEOGRAPHY(Point, 4326)`).
- `courier_positions`: append-only position events, indexed with GiST.
- `zones`: geofences as polygons.
- `events`: `entered_zone`, `left_zone` and `arrived_at_destination`, detected on every new position.

To recreate the database from scratch (this deletes all data):
```
docker compose down -v
docker compose up -d
```

## Run the API
```
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Linux/Mac: .venv/bin/pip
.venv/Scripts/python -m uvicorn app.main:app --loop app.loop:selector_loop_factory
```
Interactive docs: http://localhost:8000/docs

| Method | Path | Description |
|---|---|---|
| POST | `/positions` | Store a courier position `{courier_id, lat, lon}` |
| GET | `/couriers/{id}/position` | Latest position of a courier |
| GET | `/couriers/nearby?lat=&lon=&radius=` | Couriers within `radius` meters (default 2000), nearest first |
| GET | `/orders/{id}/nearest-courier` | Nearest available courier to an order |
| POST | `/orders/{id}/assign` | Assign a pending order to a courier `{courier_id}` |
| GET | `/events?courier_id=&limit=` | Latest events (zone enter/leave, arrival at destination) |
| GET | `/zones` | Geofences as GeoJSON |
| GET | `/health` | Health check |

The custom `--loop` is needed on Windows because psycopg async does not work with the default event loop.

## Run the simulator
With the database and the API running:
```
.venv/Scripts/python simulator/simulate.py
```
Options: `--couriers 1,2,3`, `--interval 1` (seconds), `--speed 8` (m/s), `--ticks N` (stop after N pings per courier), `--api URL`. Stop with Ctrl+C.

## Live updates (WebSocket)
Connect to `ws://localhost:8000/ws`. The server first sends the current state, then pushes every change:
```
{"type": "snapshot", "couriers": [{"courier_id", "name", "status", "lat", "lon", "recorded_at"}, ...]}
{"type": "position", "courier_id", "lat", "lon", "recorded_at", ...}
{"type": "event", "event_type", "courier_id", "zone_name", "order_id", ...}
```
Broadcasting is in-memory, so it works with a single API process.

## Live map
With the database and the API running, open http://localhost:8000/ . It shows the zones, the couriers moving in real time, an event feed, and a radius search (click the map).

To see visible movement, run the simulator faster than walking speed:
```
.venv/Scripts/python simulator/simulate.py --speed 60
```
