from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from psycopg.errors import ForeignKeyViolation
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings
from app.schemas import NearbyCourier, PositionIn, PositionOut

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
        return await cur.fetchone()


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
