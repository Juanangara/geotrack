// Leaflet uses [lat, lon]. GeoJSON and PostGIS use [lon, lat].
const COLORS = { available: "#2e9e4f", busy: "#e08a00", offline: "#888" };
const MAX_EVENTS = 20;

const map = L.map("map").setView([4.66, -74.08], 12);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const couriers = new Map(); // id -> { data, marker }
const el = (id) => document.getElementById(id);

// Build DOM with textContent only (never innerHTML) to avoid XSS
function li(...parts) {
  const item = document.createElement("li");
  parts.forEach((p) => item.append(p));
  return item;
}
function badge(status) {
  const b = document.createElement("span");
  b.className = `badge ${status}`;
  b.textContent = status;
  return b;
}

// ---- Zones (GeoJSON) ----
fetch("/zones")
  .then((r) => r.json())
  .then((geojson) => {
    L.geoJSON(geojson, {
      style: { color: "#3b6fd4", weight: 1, fillOpacity: 0.05 },
      onEachFeature: (f, layer) => layer.bindTooltip(f.properties.name, { sticky: true }),
    }).addTo(map);
  });

// ---- Couriers ----
function upsertCourier(c) {
  const known = couriers.get(c.courier_id) || {};
  const data = { ...known.data, ...c };
  if (data.lat === undefined) return; // status update for a courier we have no position for yet
  let marker = known.marker;
  if (!marker) {
    marker = L.circleMarker([data.lat, data.lon], { radius: 9, weight: 2, color: "#fff", fillOpacity: 1 })
      .bindTooltip(data.name || `#${data.courier_id}`, { permanent: true, direction: "top", offset: [0, -8] })
      .addTo(map);
  }
  marker.setLatLng([data.lat, data.lon]);
  marker.setStyle({ fillColor: COLORS[data.status] || COLORS.offline });
  couriers.set(c.courier_id, { data, marker });
  renderCouriers();
}

function renderCouriers() {
  const list = el("couriers");
  list.replaceChildren(
    ...[...couriers.values()].map(({ data }) =>
      li(data.name || `#${data.courier_id}`, badge(data.status || "offline"))
    )
  );
}

// ---- Events ----
function addEvent(e) {
  const text =
    {
      entered_zone: `entered ${e.zone_name}`,
      left_zone: `left ${e.zone_name}`,
      arrived_at_destination: `arrived (order ${e.order_id})`,
    }[e.event_type] || e.event_type;
  const who = couriers.get(e.courier_id)?.data.name || `#${e.courier_id}`;
  const time = document.createElement("span");
  time.className = "event-time";
  time.textContent = new Date(e.occurred_at).toLocaleTimeString();
  const list = el("events");
  list.prepend(li(`${who} ${text}`, time));
  while (list.children.length > MAX_EVENTS) list.lastChild.remove();

  if (e.event_type === "arrived_at_destination") {
    upsertCourier({ courier_id: e.courier_id, status: "available" });
  }
}

// ---- WebSocket with reconnect ----
let retry = 1000;
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    retry = 1000;
    el("status").className = "dot on";
    el("status").title = "connected";
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "snapshot") msg.couriers.forEach(upsertCourier);
    else if (msg.type === "position" || msg.type === "courier_status") upsertCourier(msg);
    else if (msg.type === "event") addEvent(msg);
  };
  ws.onclose = () => {
    el("status").className = "dot off";
    el("status").title = "disconnected";
    setTimeout(connect, retry);
    retry = Math.min(retry * 2, 15000);
  };
}
connect();

// ---- Radius search (calls GET /couriers/nearby) ----
let searchCircle = null;
function clearSearch() {
  if (searchCircle) map.removeLayer(searchCircle);
  searchCircle = null;
  el("nearby").replaceChildren();
}
el("clear").addEventListener("click", clearSearch);

map.on("click", async (e) => {
  const radius = Number(el("radius").value) || 2000;
  clearSearch();
  searchCircle = L.circle(e.latlng, { radius, color: "#8e44ad", weight: 1, fillOpacity: 0.08 }).addTo(map);
  const res = await fetch(`/couriers/nearby?lat=${e.latlng.lat}&lon=${e.latlng.lng}&radius=${radius}`);
  if (!res.ok) return;
  const found = await res.json();
  const list = el("nearby");
  if (found.length === 0) list.append(li("Nobody within that radius"));
  found.forEach((c) => list.append(li(c.name, `${Math.round(c.distance_m)} m`)));
});
