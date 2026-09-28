"""Runtime settings for the OpenSky extract, loaded from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


class ConfigError(ValueError):
    """Raised when settings are missing or invalid."""


@dataclass(frozen=True)
class BoundingBox:
    lamin: float
    lomin: float
    lamax: float
    lomax: float

    def __post_init__(self) -> None:
        for name in ("lamin", "lamax"):
            if not -90 <= getattr(self, name) <= 90:
                raise ConfigError(f"{name} must be between -90 and 90")
        for name in ("lomin", "lomax"):
            if not -180 <= getattr(self, name) <= 180:
                raise ConfigError(f"{name} must be between -180 and 180")
        if self.lamin >= self.lamax:
            raise ConfigError("lamin must be less than lamax")
        if self.lomin >= self.lomax:
            raise ConfigError("lomin must be less than lomax")

    @classmethod
    def parse(cls, raw: str) -> BoundingBox:
        """Parse "lamin,lomin,lamax,lomax"."""
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) != 4:
            raise ConfigError("bounding box needs 4 comma-separated values: lamin,lomin,lamax,lomax")
        try:
            values = [float(p) for p in parts]
        except ValueError as exc:
            raise ConfigError(f"bounding box values must be numbers: {raw!r}") from exc
        return cls(*values)

    def as_params(self) -> dict[str, float]:
        return {"lamin": self.lamin, "lomin": self.lomin, "lamax": self.lamax, "lomax": self.lomax}


@dataclass(frozen=True)
class Settings:
    client_id: str | None = None
    client_secret: str | None = None
    bbox: BoundingBox | None = None
    output_dir: Path = Path("data/raw")

    def __post_init__(self) -> None:
        if bool(self.client_id) != bool(self.client_secret):
            raise ConfigError("set both OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET, or neither")

    @property
    def has_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Build settings from `env`, or from os.environ plus a local .env file."""
        if env is None:
            load_dotenv(find_dotenv(usecwd=True))
            env = os.environ
        bbox_raw = env.get("OPENSKY_BBOX", "").strip()
        return cls(
            client_id=env.get("OPENSKY_CLIENT_ID", "").strip() or None,
            client_secret=env.get("OPENSKY_CLIENT_SECRET", "").strip() or None,
            bbox=BoundingBox.parse(bbox_raw) if bbox_raw else None,
            output_dir=Path(env.get("OUTPUT_DIR", "").strip() or "data/raw"),
        )
