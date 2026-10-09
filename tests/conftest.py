"""Test setup: a throwaway PostGIS database with the real schema, never the development one."""
import asyncio
import os
import sys
from pathlib import Path

import psycopg
import pytest

# psycopg async does not work with the default Windows event loop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

TEST_DB = "geotrack_test"
os.environ["POSTGRES_DB"] = TEST_DB  # must be set before app.config is imported

from app.config import settings  # noqa: E402

SQL_DIR = Path(__file__).parent.parent / "db"
BASE_URL = settings.database_url.rsplit("/", 1)[0]


@pytest.fixture(scope="session", autouse=True)
def test_database():
    with psycopg.connect(f"{BASE_URL}/postgres", autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")
    with psycopg.connect(f"{BASE_URL}/{TEST_DB}", autocommit=True) as conn:
        for sql_file in sorted(SQL_DIR.glob("*.sql")):
            if sql_file.name != "02_seed.sql":  # tests create their own data
                conn.execute(sql_file.read_text(encoding="utf-8"))
    yield
    with psycopg.connect(f"{BASE_URL}/postgres", autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


@pytest.fixture
def db(test_database):
    """Direct connection for arranging and checking data. Tables start empty in every test."""
    with psycopg.connect(f"{BASE_URL}/{TEST_DB}", autocommit=True) as conn:
        conn.execute("TRUNCATE couriers, orders, courier_positions, events RESTART IDENTITY CASCADE")
        yield conn


@pytest.fixture(scope="session")
def client(test_database):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:  # runs the lifespan (opens the connection pool)
        yield c


@pytest.fixture
def make_courier(db):
    def _make(name="Test", status="available") -> int:
        return db.execute(
            "INSERT INTO couriers (name, status) VALUES (%s, %s) RETURNING id", (name, status)
        ).fetchone()[0]

    return _make


@pytest.fixture
def make_order(db):
    def _make(lat: float, lon: float) -> int:
        return db.execute(
            "INSERT INTO orders (destination) VALUES (ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) RETURNING id",
            (lon, lat),
        ).fetchone()[0]

    return _make


@pytest.fixture
def ping(client):
    def _ping(courier_id: int, lat: float, lon: float):
        r = client.post("/positions", json={"courier_id": courier_id, "lat": lat, "lon": lon})
        assert r.status_code == 201, r.text
        return r.json()

    return _ping
