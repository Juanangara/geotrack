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
