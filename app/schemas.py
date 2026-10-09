from datetime import datetime

from pydantic import BaseModel, Field


class PositionIn(BaseModel):
    courier_id: int
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class PositionOut(BaseModel):
    id: int
    courier_id: int
    lat: float
    lon: float
    recorded_at: datetime


class NearbyCourier(BaseModel):
    courier_id: int
    name: str
    status: str
    lat: float
    lon: float
    distance_m: float
    recorded_at: datetime


class EventOut(BaseModel):
    id: int
    courier_id: int
    event_type: str
    zone_id: int | None
    zone_name: str | None = None
    order_id: int | None
    occurred_at: datetime


class AssignIn(BaseModel):
    courier_id: int


class OrderOut(BaseModel):
    id: int
    status: str
    courier_id: int | None
