"""Loader tests against a real Postgres (the docker compose warehouse)."""

import threading

import psycopg
import pytest

from extract.models import StatesSnapshot
from extract.writer import write_snapshot
from load.loader import ensure_schema, find_files, load_file, load_pending, pending_files

pytestmark = pytest.mark.integration


def count(conn, table="raw.flight_states"):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_ensure_schema_is_idempotent(db):
    ensure_schema(db)
    ensure_schema(db)
    assert count(db) == 0
    assert count(db, "raw.loaded_files") == 0


def test_loads_values_with_correct_types(db, raw_dir, valid_row):
    ensure_schema(db)
    (path,) = find_files(raw_dir)
    assert load_file(db, path, raw_dir) == 2
    row = db.execute(
        """SELECT snapshot_time, icao24, callsign, latitude, on_ground, sensors, squawk,
                  position_source, category, source_file
           FROM raw.flight_states WHERE icao24 = '4b1805'"""
    ).fetchone()
    assert row == (
        1727366405, "4b1805", "SWR123", pytest.approx(47.4581), False, None, "1000",
        0, None, path.relative_to(raw_dir).as_posix(),
    )


def test_nulls_arrays_and_categories_round_trip(db, tmp_path, valid_row):
    row = list(valid_row) + [6]
    row[12] = [11, 22]
    for i in (3, 5, 6, 7, 9, 10, 11, 13, 14):
        row[i] = None
    write_snapshot(StatesSnapshot.from_api({"time": 5, "states": [row]}), tmp_path)
    load_pending(db, tmp_path)
    got = db.execute("SELECT sensors, category, latitude, longitude, squawk FROM raw.flight_states").fetchone()
    assert got == ([11, 22], 6, None, None, None)


def test_load_pending_loads_everything_once(db, raw_dir, api_payload):
    write_snapshot(StatesSnapshot.from_api({**api_payload, "time": 1727366500}), raw_dir)
    first = load_pending(db, raw_dir)
    assert len(first.loaded) == 2 and first.rows == 4 and not first.failed
    second = load_pending(db, raw_dir)
    assert second.loaded == {} and second.rows == 0
    assert count(db) == 4


def test_reloading_a_file_does_not_duplicate(db, raw_dir):
    ensure_schema(db)
    (path,) = find_files(raw_dir)
    load_file(db, path, raw_dir)
    load_file(db, path, raw_dir)
    assert count(db) == 2
    assert count(db, "raw.loaded_files") == 1


def test_rewritten_file_is_picked_up_again(db, raw_dir, api_payload):
    load_pending(db, raw_dir)
    api_payload["states"] = api_payload["states"][:1]  # same snapshot time, fewer rows
    write_snapshot(StatesSnapshot.from_api(api_payload), raw_dir)
    assert len(pending_files(db, raw_dir)) == 1
    load_pending(db, raw_dir)
    assert count(db) == 1
    assert db.execute("SELECT row_count FROM raw.loaded_files").fetchone()[0] == 1


def test_empty_file_is_recorded_and_not_retried(db, tmp_path):
    write_snapshot(StatesSnapshot(time=7, states=[]), tmp_path)
    result = load_pending(db, tmp_path)
    assert list(result.loaded.values()) == [0]
    assert pending_files(db, tmp_path) == []


def test_bad_file_is_rolled_back_and_others_still_load(db, raw_dir, api_payload, caplog):
    good = find_files(raw_dir)[0]
    bad = write_snapshot(StatesSnapshot.from_api({**api_payload, "time": 1727366500}), raw_dir)
    bad.write_text(bad.read_text() + "{broken\n")
    result = load_pending(db, raw_dir)
    assert list(result.loaded) == [good.relative_to(raw_dir).as_posix()]
    assert list(result.failed) == [bad.relative_to(raw_dir).as_posix()]
    assert "line 3" in next(iter(result.failed.values()))
    assert count(db) == 2  # nothing from the bad file
    assert pending_files(db, raw_dir) == [bad]  # retried next run
    assert "Failed to load" in caplog.text


def test_db_error_mid_load_rolls_back(db, raw_dir):
    ensure_schema(db)
    (path,) = find_files(raw_dir)
    load_file(db, path, raw_dir)
    db.execute("ALTER TABLE raw.loaded_files ADD CONSTRAINT tiny CHECK (row_count < 1) NOT VALID")
    with pytest.raises(psycopg.errors.CheckViolation):
        load_file(db, path, raw_dir)
    assert count(db) == 2  # the earlier load is untouched, not deleted


def test_no_files(db, tmp_path):
    result = load_pending(db, tmp_path)
    assert result.loaded == {} and result.failed == {}


def test_concurrent_loads_of_same_file_do_not_duplicate(warehouse_url, db, raw_dir):
    ensure_schema(db)
    (path,) = find_files(raw_dir)
    errors = []

    def worker():
        try:
            with psycopg.connect(warehouse_url, autocommit=True) as conn:
                for _ in range(5):
                    load_file(conn, path, raw_dir)
        except Exception as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert count(db) == 2
