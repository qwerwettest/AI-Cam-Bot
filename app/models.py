from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from pydantic import BaseModel, Field, field_validator


class FindRoomQuery(BaseModel):
    location_id: str = Field(min_length=1)
    floor: int | None = None
    date: date
    time: time
    duration_minutes: int = Field(ge=15, le=480)
    min_capacity: int | None = Field(default=None, ge=1, le=500)
    need_projector: bool | None = None
    requested_by: int

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration_step(cls, value: int) -> int:
        if value % 15 != 0:
            raise ValueError("Duration must be multiple of 15 minutes.")
        return value

    def to_java_payload(self) -> dict[str, Any]:
        start_at = datetime.combine(self.date, self.time).isoformat()
        filters: dict[str, Any] = {}
        if self.min_capacity is not None:
            filters["min_capacity"] = self.min_capacity
        if self.need_projector is not None:
            filters["need_projector"] = self.need_projector

        payload: dict[str, Any] = {
            "location_id": self.location_id,
            "start_at": start_at,
            "duration_minutes": self.duration_minutes,
            "requested_by": {"telegram_user_id": self.requested_by},
        }
        if self.floor is not None:
            payload["floor"] = self.floor
        if filters:
            payload["filters"] = filters
        return payload

