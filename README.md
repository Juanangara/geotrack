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

To recreate the database from scratch (this deletes all data):
```
docker compose down -v
docker compose up -d
```
