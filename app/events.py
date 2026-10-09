"""Event detection: compares a courier's new position with the previous one."""

ARRIVAL_RADIUS_M = 30


async def _zones_covering(conn, position_id: int) -> set[int]:
    cur = await conn.execute(
        """
        SELECT z.id FROM zones z, courier_positions p
        WHERE p.id = %s AND ST_Covers(z.area, p.position)
        """,
        (position_id,),
    )
    return {row["id"] for row in await cur.fetchall()}


async def _insert_event(conn, courier_id, event_type, zone_id=None, order_id=None) -> dict:
    cur = await conn.execute(
        """
        WITH e AS (
            INSERT INTO events (courier_id, event_type, zone_id, order_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id, courier_id, event_type, zone_id, order_id, occurred_at
        )
        SELECT e.*, z.name AS zone_name FROM e LEFT JOIN zones z ON z.id = e.zone_id
        """,
        (courier_id, event_type, zone_id, order_id),
    )
    return await cur.fetchone()


async def detect_events(conn, courier_id: int, position_id: int) -> list[dict]:
    """Runs inside the same transaction that inserted the position."""
    events = []

    # Geofences: set difference between the previous and the new position
    cur = await conn.execute(
        "SELECT id FROM courier_positions WHERE courier_id = %s AND id < %s ORDER BY id DESC LIMIT 1",
        (courier_id, position_id),
    )
    previous = await cur.fetchone()
    zones_before = await _zones_covering(conn, previous["id"]) if previous else set()
    zones_now = await _zones_covering(conn, position_id)

    for zone_id in sorted(zones_now - zones_before):
        events.append(await _insert_event(conn, courier_id, "entered_zone", zone_id=zone_id))
    for zone_id in sorted(zones_before - zones_now):
        events.append(await _insert_event(conn, courier_id, "left_zone", zone_id=zone_id))

    # Arrival: assigned order whose destination is within ARRIVAL_RADIUS_M
    cur = await conn.execute(
        """
        UPDATE orders o SET status = 'delivered'
        FROM courier_positions p
        WHERE p.id = %s AND o.courier_id = %s AND o.status = 'assigned'
          AND ST_DWithin(o.destination, p.position, %s)
        RETURNING o.id
        """,
        (position_id, courier_id, ARRIVAL_RADIUS_M),
    )
    for row in await cur.fetchall():
        events.append(await _insert_event(conn, courier_id, "arrived_at_destination", order_id=row["id"]))
        await conn.execute(
            """
            UPDATE couriers SET status = 'available'
            WHERE id = %s AND NOT EXISTS (
                SELECT 1 FROM orders WHERE courier_id = %s AND status = 'assigned')
            """,
            (courier_id, courier_id),
        )
    return events
