"""Raw files -> loader -> dbt build -> marts, against the test database.

Needs the docker compose warehouse and the dbt environment (`make setup`).
"""

import os
import subprocess
from pathlib import Path

import pytest

from extract.models import StatesSnapshot
from extract.writer import write_snapshot
from load.loader import load_pending

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[1]
DBT_BIN = Path(os.environ.get("DBT_BIN", ROOT / ".venv-dbt" / "bin" / "dbt"))
T0 = 1727366400  # 2024-09-26 16:00:00 UTC


def state(icao24, callsign, country="Switzerland", on_ground=False, lat=47.0):
    return [icao24, callsign, country, T0, T0, 8.5, lat, 10000.0, on_ground, 230.0, 90.0, 0.0,
            None, 10100.0, "1000", False, 0]


@pytest.fixture
def dbt_build(warehouse_url, db, tmp_path):
    if not DBT_BIN.exists():
        pytest.skip(f"dbt not installed at {DBT_BIN} (run `make setup`)")
    for schema in ("staging", "marts"):
        db.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    info = db.info

    def run(*args):
        env = {
            **os.environ,
            "WAREHOUSE_HOST": info.host,
            "WAREHOUSE_PORT": str(info.port),
            "WAREHOUSE_USER": info.user,
            "WAREHOUSE_PASSWORD": info.password,
            "WAREHOUSE_DB": info.dbname,
        }
        return subprocess.run(
            [str(DBT_BIN), *args, "--project-dir", str(ROOT / "dbt"), "--profiles-dir", str(ROOT / "dbt"),
             "--target-path", str(tmp_path / "target"), "--log-path", str(tmp_path / "logs")],
            env=env, capture_output=True, text=True, timeout=300,
        )

    return run


def test_raw_files_become_flights(db, tmp_path, dbt_build):
    raw = tmp_path / "raw"
    snapshots = {
        T0: [state("aaaaaa", "SWR1"), state("bbbbbb", "DLH1", country="Germany")],
        T0 + 300: [state("aaaaaa", "SWR1"), state("bbbbbb", "DLH1", country="Germany", on_ground=True)],
        # aaaaaa disappears for 40 minutes, then comes back: a second flight.
        T0 + 2700: [state("aaaaaa", "SWR2")],
    }
    for t, rows in snapshots.items():
        write_snapshot(StatesSnapshot.from_api({"time": t, "states": rows}), raw)
    assert load_pending(db, raw).rows == 5

    result = dbt_build("build")
    assert result.returncode == 0, result.stdout[-3000:]

    flights = db.execute(
        "SELECT icao24, callsign, observations, duration_seconds, seen_on_ground, is_ongoing "
        "FROM marts.fct_flights ORDER BY icao24, first_seen_at"
    ).fetchall()
    assert flights == [
        ("aaaaaa", "SWR1", 2, 300, False, False),
        ("aaaaaa", "SWR2", 1, 0, False, True),
        ("bbbbbb", "DLH1", 2, 300, True, False),
    ]

    aircraft = db.execute("SELECT icao24, latest_callsign, flights FROM marts.dim_aircraft ORDER BY 1").fetchall()
    assert aircraft == [("aaaaaa", "SWR2", 2), ("bbbbbb", "DLH1", 1)]

    hourly = db.execute(
        "SELECT origin_country, aircraft, observations FROM marts.agg_hourly_traffic "
        "WHERE hour = to_timestamp(%s) ORDER BY 1",
        (T0,),
    ).fetchall()
    assert hourly == [("Germany", 1, 2), ("Switzerland", 1, 3)]


def test_dbt_build_is_rerunnable(db, tmp_path, dbt_build):
    raw = tmp_path / "raw"
    write_snapshot(StatesSnapshot.from_api({"time": T0, "states": [state("aaaaaa", "SWR1")]}), raw)
    load_pending(db, raw)
    for _ in range(2):
        result = dbt_build("build")
        assert result.returncode == 0, result.stdout[-3000:]
    assert db.execute("SELECT count(*) FROM marts.fct_flights").fetchone()[0] == 1


def test_dbt_build_on_empty_raw_table(db, dbt_build):
    from load.loader import ensure_schema

    ensure_schema(db)
    result = dbt_build("build")
    assert result.returncode == 0, result.stdout[-3000:]
    assert db.execute("SELECT count(*) FROM marts.fct_flights").fetchone()[0] == 0


def test_dbt_data_tests_catch_bad_data(db, tmp_path, dbt_build):
    """Bad rows that slip past the loader must fail `dbt build`, not pass silently."""
    raw = tmp_path / "raw"
    write_snapshot(StatesSnapshot.from_api({"time": T0, "states": [state("aaaaaa", "SWR1")]}), raw)
    load_pending(db, raw)
    db.execute("UPDATE raw.flight_states SET latitude = 123")
    result = dbt_build("build")
    assert result.returncode != 0
    assert "accepted_range_stg_flight_states_latitude" in result.stdout
