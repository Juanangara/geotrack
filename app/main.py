from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.staticfiles import StaticFiles
from psycopg.errors import ForeignKeyViolation
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings
from app.events import detect_events
from app.realtime import manager
from app.schemas import AssignIn, EventOut, NearbyCourier, OrderOut, PositionIn, PositionOut

POSITION_COLUMNS = """
    id, courier_id,
    ST_Y(position::geometry) AS lat,
    ST_X(position::geometry) AS lon,
    recorded_at
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = AsyncConnectionPool(
        settings.database_url, open=False, kwargs={"row_factory": dict_row}
    )
    await app.state.pool.open()
    yield
    await app.state.pool.close()


app = FastAPI(title="geotrack", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/positions", response_model=PositionOut, status_code=201)
async def create_position(pos: PositionIn):
    async with app.state.pool.connection() as conn:
        async with conn.transaction():
            try:
                cur = await conn.execute(
                    f"""
                    INSERT INTO courier_positions (courier_id, position)
                    VALUES (%s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography)
                    RETURNING {POSITION_COLUMNS}
                    """,
                    (pos.courier_id, pos.lon, pos.lat),
                )
            except ForeignKeyViolation:
                raise HTTPException(status_code=404, detail="Courier not found")
            row = await cur.fetchone()
            events = await detect_events(conn, pos.courier_id, row["id"])
    # Broadcast only after the transaction has been committed
    await manager.broadcast({"type": "position", **row})
    for event in events:
        await manager.broadcast({"type": "event", **event})
    return row


@app.get("/couriers/{courier_id}/position", response_model=PositionOut)
async def last_position(courier_id: int):
    async with app.state.pool.connection() as conn:
        cur = await conn.execute(
            f"""
            SELECT {POSITION_COLUMNS} FROM courier_positions
            WHERE courier_id = %s
            ORDER BY recorded_at DESC LIMIT 1
            """,
            (courier_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No positions for this courier")
    return row


# Each courier's latest position (uses the (courier_id, recorded_at DESC) index)
LATEST_POSITION = """
    CROSS JOIN LATERAL (
        SELECT position, recorded_at FROM courier_positions
        WHERE courier_id = c.id
        ORDER BY recorded_at DESC LIMIT 1
    ) p
"""

NEARBY_COLUMNS = """
    c.id AS courier_id, c.name, c.status,
    ST_Y(p.position::geometry) AS lat,
    ST_X(p.position::geometry) AS lon,
    ST_Distance(p.position, q.pt) AS distance_m,
    p.recorded_at
"""


@app.get("/couriers/nearby", response_model=list[NearbyCourier])
async def couriers_nearby(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius: float = Query(2000, gt=0, le=50_000, description="meters"),
):
    async with app.state.pool.connection() as conn:
        cur = await conn.execute(
            f"""
            WITH q AS (SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS pt)
            SELECT {NEARBY_COLUMNS}
            FROM couriers c CROSS JOIN q {LATEST_POSITION}
            WHERE c.status <> 'offline' AND ST_DWithin(p.position, q.pt, %s)
            ORDER BY distance_m
            """,
            (lon, lat, radius),
        )
        return await cur.fetchall()


@app.get("/orders/{order_id}/nearest-courier", response_model=NearbyCourier)
async def nearest_courier(order_id: int):
    async with app.state.pool.connection() as conn:
        cur = await conn.execute(
            f"""
            WITH q AS (SELECT destination AS pt FROM orders WHERE id = %s)
            SELECT {NEARBY_COLUMNS}
            FROM couriers c CROSS JOIN q {LATEST_POSITION}
            WHERE c.status = 'available'
            ORDER BY distance_m LIMIT 1
            """,
            (order_id,),
        )
        row = await cur.fetchone()
        if row is None:
            exists = await (await conn.execute("SELECT 1 FROM orders WHERE id = %s", (order_id,))).fetchone()
            detail = "No available courier" if exists else "Order not found"
            raise HTTPException(status_code=404, detail=detail)
        return row


@app.post("/orders/{order_id}/assign", response_model=OrderOut)
async def assign_order(order_id: int, body: AssignIn):
    async with app.state.pool.connection() as conn:
        async with conn.transaction():
            try:
                cur = await conn.execute(
                    """
                    UPDATE orders SET courier_id = %s, status = 'assigned'
                    WHERE id = %s AND status = 'pending'
                    RETURNING id, status, courier_id
                    """,
                    (body.courier_id, order_id),
                )
            except ForeignKeyViolation:
                raise HTTPException(status_code=404, detail="Courier not found")
            row = await cur.fetchone()
            if row is None:
                raise HTTPException(status_code=409, detail="Order not found or not pending")
            await conn.execute("UPDATE couriers SET status = 'busy' WHERE id = %s", (body.courier_id,))
    await manager.broadcast({"type": "courier_status", "courier_id": body.courier_id, "status": "busy"})
    return row


@app.get("/events", response_model=list[EventOut])
async def list_events(courier_id: int | None = None, limit: int = Query(50, ge=1, le=500)):
    async with app.state.pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT e.id, e.courier_id, e.event_type, e.zone_id, z.name AS zone_name,
                   e.order_id, e.occurred_at
            FROM events e LEFT JOIN zones z ON z.id = e.zone_id
            WHERE (%s::int IS NULL OR e.courier_id = %s)
            ORDER BY e.id DESC LIMIT %s
            """,
            (courier_id, courier_id, limit),
        )
        return await cur.fetchall()


SNAPSHOT_QUERY = f"""
    SELECT c.id AS courier_id, c.name, c.status,
           ST_Y(p.position::geometry) AS lat,
           ST_X(p.position::geometry) AS lon,
           p.recorded_at
    FROM couriers c {LATEST_POSITION}
    ORDER BY c.id
"""


@app.websocket("/ws")
async def live(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Current state first, then live updates arrive through manager.broadcast
        async with app.state.pool.connection() as conn:
            cur = await conn.execute(SNAPSHOT_QUERY)
            couriers = await cur.fetchall()
        await ws.send_json(jsonable_encoder({"type": "snapshot", "couriers": couriers}))
        while True:
            await ws.receive_text()  # keeps the connection open; raises on disconnect
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)


@app.get("/zones")
async def zones():
    """Geofences as a GeoJSON FeatureCollection (coordinates are [lon, lat])."""
    async with app.state.pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, name, ST_AsGeoJSON(area::geometry)::json AS geometry FROM zones ORDER BY id"
        )
        rows = await cur.fetchall()
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"id": r["id"], "name": r["name"]}, "geometry": r["geometry"]}
            for r in rows
        ],
    }


# Must be last: it serves the web/ folder at "/" and would shadow later routes
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "web", html=True), name="web")
