CREATE EXTENSION IF NOT EXISTS postgis;

-- Couriers who deliver orders
CREATE TABLE couriers (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'available'
               CHECK (status IN ('available', 'busy', 'offline')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Orders with a delivery destination
CREATE TABLE orders (
    id          SERIAL PRIMARY KEY,
    destination GEOGRAPHY(Point, 4326) NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'assigned', 'delivered')),
    courier_id  INTEGER REFERENCES couriers(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Position events: append-only, one row per GPS ping
CREATE TABLE courier_positions (
    id          BIGSERIAL PRIMARY KEY,
    courier_id  INTEGER NOT NULL REFERENCES couriers(id),
    position    GEOGRAPHY(Point, 4326) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Spatial indexes (GiST) for proximity queries
CREATE INDEX idx_positions_position ON courier_positions USING GIST (position);
CREATE INDEX idx_orders_destination ON orders USING GIST (destination);

-- Latest position per courier
CREATE INDEX idx_positions_courier_time ON courier_positions (courier_id, recorded_at DESC);
