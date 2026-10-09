"""Behavior tests against the real API and a real PostGIS database."""

# A point away from the sample zones, so zone events do not interfere
LAT, LON = 6.2442, -75.5812
# 0.01 degrees of latitude is about 1.1 km
NORTH_1KM = LAT + 0.01
NORTH_3KM = LAT + 0.03


def test_position_is_stored_and_latest_is_returned(client, make_courier, ping):
    courier = make_courier()
    ping(courier, 4.60, -74.10)
    ping(courier, 4.61, -74.11)

    r = client.get(f"/couriers/{courier}/position")
    assert r.status_code == 200
    assert (r.json()["lat"], r.json()["lon"]) == (4.61, -74.11)  # lat/lon not swapped


def test_invalid_position_is_rejected(client, make_courier):
    courier = make_courier()
    assert client.post("/positions", json={"courier_id": courier, "lat": 200, "lon": 0}).status_code == 422
    assert client.post("/positions", json={"courier_id": courier, "lat": 0, "lon": 200}).status_code == 422
    assert client.post("/positions", json={"courier_id": 999, "lat": 0, "lon": 0}).status_code == 404


def test_nearby_respects_radius_and_orders_by_distance(client, make_courier, ping):
    near = make_courier("near")
    far = make_courier("far")
    ping(near, NORTH_1KM, LON)
    ping(far, NORTH_3KM, LON)

    def nearby(radius):
        r = client.get("/couriers/nearby", params={"lat": LAT, "lon": LON, "radius": radius})
        assert r.status_code == 200
        return r.json()

    assert [c["name"] for c in nearby(500)] == []
    assert [c["name"] for c in nearby(2000)] == ["near"]
    both = nearby(5000)
    assert [c["name"] for c in both] == ["near", "far"]
    assert 1090 < both[0]["distance_m"] < 1120  # real meters, thanks to geography


def test_nearby_uses_latest_position_and_skips_offline(client, make_courier, ping):
    moving = make_courier("moving")
    offline = make_courier("offline", status="offline")
    ping(moving, NORTH_1KM, LON)
    ping(moving, NORTH_3KM, LON)  # moved away: the old position must not count
    ping(offline, NORTH_1KM, LON)

    r = client.get("/couriers/nearby", params={"lat": LAT, "lon": LON, "radius": 2000})
    assert r.json() == []


def test_nearest_courier_ignores_busy_ones(client, make_courier, make_order, ping):
    order = make_order(LAT, LON)
    busy_but_closest = make_courier("busy", status="busy")
    available_near = make_courier("available_near")
    available_far = make_courier("available_far")
    ping(busy_but_closest, LAT + 0.001, LON)
    ping(available_near, NORTH_1KM, LON)
    ping(available_far, NORTH_3KM, LON)

    r = client.get(f"/orders/{order}/nearest-courier")
    assert r.status_code == 200
    assert r.json()["name"] == "available_near"


def test_nearest_courier_not_found_cases(client, make_order):
    assert client.get("/orders/999/nearest-courier").status_code == 404
    order = make_order(LAT, LON)
    assert client.get(f"/orders/{order}/nearest-courier").status_code == 404  # nobody available


def test_zone_events_on_entering_and_leaving(client, make_courier, ping):
    courier = make_courier()
    ping(courier, 4.63, -74.10)  # Centro (first ping: entered)
    ping(courier, 4.64, -74.10)  # still Centro: nothing new
    ping(courier, 4.70, -74.10)  # Norte

    events = client.get("/events", params={"courier_id": courier}).json()
    seen = [(e["event_type"], e["zone_name"]) for e in reversed(events)]  # oldest first
    assert seen == [
        ("entered_zone", "Centro"),
        ("entered_zone", "Norte"),
        ("left_zone", "Centro"),
    ]


def test_arrival_marks_order_delivered_and_frees_courier(client, db, make_courier, make_order, ping):
    courier = make_courier()
    order = make_order(LAT, LON)
    assert client.post(f"/orders/{order}/assign", json={"courier_id": courier}).status_code == 200
    assert db.execute("SELECT status FROM couriers WHERE id = %s", (courier,)).fetchone()[0] == "busy"

    ping(courier, LAT + 0.01, LON)  # 1 km away: not arrived yet
    assert db.execute("SELECT status FROM orders WHERE id = %s", (order,)).fetchone()[0] == "assigned"

    ping(courier, LAT + 0.00005, LON)  # about 5 m away
    assert db.execute("SELECT status FROM orders WHERE id = %s", (order,)).fetchone()[0] == "delivered"
    assert db.execute("SELECT status FROM couriers WHERE id = %s", (courier,)).fetchone()[0] == "available"
    types = [e["event_type"] for e in client.get("/events", params={"courier_id": courier}).json()]
    assert "arrived_at_destination" in types


def test_order_can_only_be_assigned_once(client, make_courier, make_order):
    courier = make_courier()
    order = make_order(LAT, LON)
    assert client.post(f"/orders/{order}/assign", json={"courier_id": courier}).status_code == 200
    assert client.post(f"/orders/{order}/assign", json={"courier_id": courier}).status_code == 409


def test_zones_endpoint_returns_geojson(client):
    data = client.get("/zones").json()
    assert data["type"] == "FeatureCollection"
    assert {f["properties"]["name"] for f in data["features"]} == {"Norte", "Centro", "Sur"}
    assert data["features"][0]["geometry"]["type"] == "Polygon"


def test_websocket_sends_snapshot_then_live_updates(client, make_courier, ping):
    courier = make_courier("Ana")
    ping(courier, 4.63, -74.10)

    with client.websocket_connect("/ws") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert snapshot["couriers"][0]["name"] == "Ana"

        ping(courier, 4.70, -74.10)  # crosses from Centro to Norte
        types = [ws.receive_json()["type"] for _ in range(3)]
        assert types == ["position", "event", "event"]
