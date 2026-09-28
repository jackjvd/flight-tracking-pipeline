import json

import pytest

from extract.models import StatesSnapshot
from extract.writer import snapshot_path, write_snapshot


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_snapshot_path_partitions_by_utc_date(tmp_path):
    # 1727395199 is 2024-09-26 23:59:59 UTC; 1727395200 is the next day.
    assert snapshot_path(tmp_path, 1727395199) == tmp_path / "states/date=2024-09-26/states_1727395199.ndjson"
    assert snapshot_path(tmp_path, 1727395200).parent.name == "date=2024-09-27"


def test_writes_one_line_per_state(tmp_path, api_payload):
    snapshot = StatesSnapshot.from_api(api_payload)
    path = write_snapshot(snapshot, tmp_path)
    records = read_lines(path)
    assert len(records) == 2
    assert records[0]["snapshot_time"] == 1727366405
    assert records[0]["icao24"] == "4b1805"
    assert records[0]["callsign"] == "SWR123"
    assert set(records[0]) >= {"latitude", "longitude", "on_ground", "category"}


def test_creates_missing_directories(tmp_path, api_payload):
    path = write_snapshot(StatesSnapshot.from_api(api_payload), tmp_path / "does" / "not" / "exist")
    assert path.exists()


def test_empty_snapshot_writes_empty_file(tmp_path):
    path = write_snapshot(StatesSnapshot(time=1727366405, states=[]), tmp_path)
    assert path.exists()
    assert path.read_text() == ""


def test_rerun_overwrites_instead_of_duplicating(tmp_path, api_payload):
    snapshot = StatesSnapshot.from_api(api_payload)
    first = write_snapshot(snapshot, tmp_path)
    second = write_snapshot(snapshot, tmp_path)
    assert first == second
    assert len(read_lines(second)) == 2
    assert len(list(first.parent.iterdir())) == 1


def test_no_temp_file_left_on_failure(tmp_path, api_payload, monkeypatch):
    snapshot = StatesSnapshot.from_api(api_payload)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("extract.writer.os.replace", boom)
    with pytest.raises(OSError, match="disk full"):
        write_snapshot(snapshot, tmp_path)
    assert list(snapshot_path(tmp_path, snapshot.time).parent.iterdir()) == []


def test_unicode_is_preserved(tmp_path, valid_row):
    valid_row[2] = "Côte d'Ivoire"
    snapshot = StatesSnapshot.from_api({"time": 1, "states": [valid_row]})
    assert read_lines(write_snapshot(snapshot, tmp_path))[0]["origin_country"] == "Côte d'Ivoire"
