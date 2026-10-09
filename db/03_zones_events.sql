-- Geofences: named polygons
CREATE TABLE zones (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    area GEOGRAPHY(Polygon, 4326) NOT NULL
);
CREATE INDEX idx_zones_area ON zones USING GIST (area);

-- Events detected from position updates: append-only
CREATE TABLE events (
    id          BIGSERIAL PRIMARY KEY,
    courier_id  INTEGER NOT NULL REFERENCES couriers(id),
    event_type  TEXT NOT NULL
                CHECK (event_type IN ('entered_zone', 'left_zone', 'arrived_at_destination')),
    zone_id     INTEGER REFERENCES zones(id),
    order_id    INTEGER REFERENCES orders(id),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_events_courier_time ON events (courier_id, occurred_at DESC);

-- Sample zones: three horizontal bands over Bogota
-- ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, srid)
INSERT INTO zones (name, area) VALUES
    ('Norte',  ST_MakeEnvelope(-74.15, 4.67, -74.02, 4.78, 4326)::geography),
    ('Centro', ST_MakeEnvelope(-74.15, 4.60, -74.02, 4.67, 4326)::geography),
    ('Sur',    ST_MakeEnvelope(-74.15, 4.55, -74.02, 4.60, 4326)::geography);
