"""Typed models for the OpenSky /states/all response.

OpenSky returns each aircraft as a positional array; see
https://openskynetwork.github.io/opensky-api/rest.html#all-state-vectors
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

log = logging.getLogger(__name__)

STATE_FIELDS = (
    "icao24",
    "callsign",
    "origin_country",
    "time_position",
    "last_contact",
    "longitude",
    "latitude",
    "baro_altitude",
    "on_ground",
    "velocity",
    "true_track",
    "vertical_rate",
    "sensors",
    "geo_altitude",
    "squawk",
    "spi",
    "position_source",
    "category",  # only present when extended=1 is requested
)
REQUIRED_FIELD_COUNT = 17


class StateVector(BaseModel):
    icao24: str = Field(pattern=r"^[0-9a-f]{6}$")
    callsign: str | None
    origin_country: str
    time_position: int | None
    last_contact: int
    longitude: float | None = Field(ge=-180, le=180)
    latitude: float | None = Field(ge=-90, le=90)
    baro_altitude: float | None
    on_ground: bool
    velocity: float | None = Field(ge=0)
    true_track: float | None
    vertical_rate: float | None
    sensors: list[int] | None
    geo_altitude: float | None
    squawk: str | None
    spi: bool
    position_source: int = Field(ge=0, le=3)
    category: int | None = None

    @field_validator("icao24", mode="before")
    @classmethod
    def _normalize_icao24(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("callsign", "squawk", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @classmethod
    def from_row(cls, row: list[Any]) -> StateVector:
        if not isinstance(row, list) or len(row) < REQUIRED_FIELD_COUNT:
            raise ValueError(f"expected at least {REQUIRED_FIELD_COUNT} fields, got {row!r}")
        return cls.model_validate(dict(zip(STATE_FIELDS, row)))


class StatesSnapshot(BaseModel):
    time: int
    states: list[StateVector]
    skipped: int = 0

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> StatesSnapshot:
        """Parse an API response, dropping (and counting) rows that fail validation."""
        if not isinstance(payload, dict) or not isinstance(payload.get("time"), int):
            raise ValueError("response is missing an integer 'time' field")
        states: list[StateVector] = []
        skipped = 0
        # OpenSky sends "states": null when nothing is in the area.
        for row in payload.get("states") or []:
            try:
                states.append(StateVector.from_row(row))
            except (ValueError, ValidationError) as exc:
                skipped += 1
                log.warning("Skipping malformed state row: %s", exc)
        return cls(time=payload["time"], states=states, skipped=skipped)
