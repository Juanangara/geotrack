"""In-memory pub/sub: keeps the open WebSockets and broadcasts messages to all of them."""
import asyncio

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.connections.discard(ws)

    async def broadcast(self, message: dict) -> None:
        payload = jsonable_encoder(message)  # datetimes -> strings
        await asyncio.gather(*(self._send(ws, payload) for ws in list(self.connections)))

    async def _send(self, ws: WebSocket, payload: dict) -> None:
        try:
            await ws.send_json(payload)
        except Exception:  # client went away: drop it
            self.disconnect(ws)


manager = ConnectionManager()
