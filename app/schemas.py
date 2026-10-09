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
