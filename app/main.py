from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from psycopg.errors import ForeignKeyViolation
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings
from app.schemas import PositionIn, PositionOut

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
