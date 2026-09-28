"""Load raw NDJSON snapshots from the extract step into Postgres.

Each file is loaded in its own transaction: its old rows are deleted and the
file is inserted again, so loading the same file twice never duplicates data.
raw.loaded_files records what has been loaded, so each run only picks up new
or changed files.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from pydantic import ValidationError

from extract.models import StateVector

log = logging.getLogger(__name__)

COLUMNS = (
    "snapshot_time",
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
    "category",
    "source_file",
)
COLUMN_TYPES = (
    "int8", "text", "text", "text", "int8", "int8", "float8", "float8", "float8", "bool",
    "float8", "float8", "float8", "int4[]", "float8", "text", "bool", "int2", "int2", "text",
)

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.flight_states (
    snapshot_time   bigint           NOT NULL,
    icao24          text             NOT NULL,
    callsign        text,
    origin_country  text             NOT NULL,
    time_position   bigint,
    last_contact    bigint           NOT NULL,
    longitude       double precision,
    latitude        double precision,
    baro_altitude   double precision,
    on_ground       boolean          NOT NULL,
    velocity        double precision,
    true_track      double precision,
    vertical_rate   double precision,
    sensors         integer[],
    geo_altitude    double precision,
    squawk          text,
    spi             boolean          NOT NULL,
    position_source smallint         NOT NULL,
    category        smallint,
    source_file     text             NOT NULL,
    loaded_at       timestamptz      NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS flight_states_source_file_idx ON raw.flight_states (source_file);
CREATE INDEX IF NOT EXISTS flight_states_snapshot_time_idx ON raw.flight_states (snapshot_time);

CREATE TABLE IF NOT EXISTS raw.loaded_files (
    source_file text        PRIMARY KEY,
    file_size   bigint      NOT NULL,
    row_count   integer     NOT NULL,
    loaded_at   timestamptz NOT NULL DEFAULT now()
);
"""


class LoadError(ValueError):
    """Raised when a raw file cannot be parsed or validated."""


@dataclass
class LoadResult:
    loaded: dict[str, int] = field(default_factory=dict)  # source_file -> rows
    failed: dict[str, str] = field(default_factory=dict)  # source_file -> error

    @property
    def rows(self) -> int:
        return sum(self.loaded.values())


def ensure_schema(conn: psycopg.Connection) -> None:
    with conn.transaction():
        conn.execute(SCHEMA_SQL)


def find_files(input_dir: Path) -> list[Path]:
    """All snapshot files, oldest first. In-progress .tmp files are ignored."""
    return sorted((Path(input_dir) / "states").glob("date=*/states_*.ndjson"))


def read_rows(path: Path, source_file: str) -> list[tuple]:
    """Parse and validate every line of a file, or raise LoadError."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                snapshot_time = record.pop("snapshot_time")
                if not isinstance(snapshot_time, int) or isinstance(snapshot_time, bool):
                    raise ValueError("snapshot_time must be an integer")
                state = StateVector.model_validate(record)
            except (ValueError, KeyError, TypeError, AttributeError, ValidationError) as exc:
                raise LoadError(f"{source_file} line {line_no}: {exc}") from exc
            values = state.model_dump()
            rows.append((snapshot_time, *(values[c] for c in COLUMNS[1:-1]), source_file))
    return rows


def pending_files(conn: psycopg.Connection, input_dir: Path) -> list[Path]:
    """Files that have not been loaded yet, or whose size changed since loading."""
    loaded = dict(conn.execute("SELECT source_file, file_size FROM raw.loaded_files").fetchall())
    return [
        path
        for path in find_files(input_dir)
        if loaded.get(_source_name(path, input_dir)) != path.stat().st_size
    ]


def load_file(conn: psycopg.Connection, path: Path, input_dir: Path) -> int:
    """Replace the rows for one file. Returns the number of rows loaded."""
    source_file = _source_name(path, input_dir)
    file_size = path.stat().st_size
    rows = read_rows(path, source_file)
    with conn.transaction():
        # Serialize concurrent loads of the same file (e.g. overlapping Airflow runs).
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (source_file,))
        conn.execute("DELETE FROM raw.flight_states WHERE source_file = %s", (source_file,))
        with conn.cursor() as cur:
            with cur.copy(f"COPY raw.flight_states ({', '.join(COLUMNS)}) FROM STDIN") as copy:
                copy.set_types(COLUMN_TYPES)
                for row in rows:
                    copy.write_row(row)
        conn.execute(
            """
            INSERT INTO raw.loaded_files (source_file, file_size, row_count)
            VALUES (%s, %s, %s)
            ON CONFLICT (source_file) DO UPDATE
            SET file_size = EXCLUDED.file_size, row_count = EXCLUDED.row_count, loaded_at = now()
            """,
            (source_file, file_size, len(rows)),
        )
    return len(rows)


def load_pending(conn: psycopg.Connection, input_dir: Path) -> LoadResult:
    """Load every pending file. A bad file is recorded and skipped; the rest still load."""
    ensure_schema(conn)
    result = LoadResult()
    for path in pending_files(conn, input_dir):
        source_file = _source_name(path, input_dir)
        try:
            result.loaded[source_file] = load_file(conn, path, input_dir)
        except (LoadError, OSError) as exc:
            log.error("Failed to load %s: %s", source_file, exc)
            result.failed[source_file] = str(exc)
    return result


def _source_name(path: Path, input_dir: Path) -> str:
    # Stored relative to the input dir so the data folder can move.
    return Path(path).relative_to(input_dir).as_posix()
