import pytest

# A realistic 17-field row as returned by /states/all.
VALID_ROW = [
    "4b1805", "SWR123  ", "Switzerland", 1727366400, 1727366401,
    8.5492, 47.4581, 10972.8, False, 231.4, 87.2, 0.0,
    None, 11247.1, "1000", False, 0,
]


@pytest.fixture
def valid_row():
    return list(VALID_ROW)


@pytest.fixture
def api_payload(valid_row):
    second = list(valid_row)
    second[0], second[1] = "a1b2c3", "UAL9    "
    return {"time": 1727366405, "states": [valid_row, second]}


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Keep a developer's real .env and OPENSKY_* variables out of tests."""
    for var in ("OPENSKY_CLIENT_ID", "OPENSKY_CLIENT_SECRET", "OPENSKY_BBOX", "OUTPUT_DIR", "WAREHOUSE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)


# --- Postgres fixtures for integration tests ---------------------------------

import os  # noqa: E402

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402

TEST_DB = "flights_test"


@pytest.fixture(scope="session")
def warehouse_url():
    """URL of a throwaway test database, created on the docker compose warehouse.

    Override the server with TEST_WAREHOUSE_URL. Tests are skipped if it is not reachable.
    """
    admin_url = os.environ.get("TEST_WAREHOUSE_URL", "postgresql://flights:flights@localhost:5432/flights")
    try:
        with psycopg.connect(admin_url, autocommit=True, connect_timeout=3) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone()
            if not exists:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable (run `docker compose up -d warehouse`): {exc}")
    return psycopg.conninfo.make_conninfo(admin_url, dbname=TEST_DB)


@pytest.fixture
def db(warehouse_url):
    """A connection to an empty test database (the raw schema is dropped first)."""
    with psycopg.connect(warehouse_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS raw CASCADE")
        yield conn


@pytest.fixture
def raw_dir(tmp_path, api_payload):
    """A raw data folder containing one snapshot written by the extract step."""
    from extract.models import StatesSnapshot
    from extract.writer import write_snapshot

    root = tmp_path / "raw"
    write_snapshot(StatesSnapshot.from_api(api_payload), root)
    return root
