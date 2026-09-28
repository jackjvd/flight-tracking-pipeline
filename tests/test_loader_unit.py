"""Loader tests that don't need a database."""

import json

import pytest

from extract.models import StatesSnapshot
from extract.writer import write_snapshot
from load.loader import COLUMN_TYPES, COLUMNS, LoadError, LoadResult, find_files, read_rows


def write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in lines))
    return path


@pytest.fixture
def record(raw_dir):
    (path,) = find_files(raw_dir)
    return json.loads(path.read_text().splitlines()[0])


def test_columns_and_types_line_up():
    assert len(COLUMNS) == len(COLUMN_TYPES)
    assert COLUMNS[0] == "snapshot_time" and COLUMNS[-1] == "source_file"


class TestFindFiles:
    def test_finds_snapshot_files_sorted(self, tmp_path, api_payload):
        for t in (1727366500, 1727366405, 1727452800):
            write_snapshot(StatesSnapshot.from_api({**api_payload, "time": t}), tmp_path)
        names = [p.name for p in find_files(tmp_path)]
        assert names == ["states_1727366405.ndjson", "states_1727366500.ndjson", "states_1727452800.ndjson"]

    def test_ignores_temp_and_unrelated_files(self, raw_dir):
        day = find_files(raw_dir)[0].parent
        (day / "tmpabc.tmp").write_text("partial")
        (day / "notes.txt").write_text("x")
        (raw_dir / "states_1.ndjson").write_text("")  # not in a date= folder
        assert len(find_files(raw_dir)) == 1

    def test_missing_dir_returns_empty(self, tmp_path):
        assert find_files(tmp_path / "nope") == []


class TestReadRows:
    def test_reads_rows_in_column_order(self, raw_dir):
        (path,) = find_files(raw_dir)
        rows = read_rows(path, "src.ndjson")
        assert len(rows) == 2
        row = dict(zip(COLUMNS, rows[0]))
        assert row["snapshot_time"] == 1727366405
        assert row["icao24"] == "4b1805"
        assert row["callsign"] == "SWR123"
        assert row["on_ground"] is False
        assert row["source_file"] == "src.ndjson"
        assert len(rows[0]) == len(COLUMNS)

    def test_empty_file(self, tmp_path):
        assert read_rows(write_lines(tmp_path / "f.ndjson", []), "f") == []

    def test_blank_lines_ignored(self, tmp_path, record):
        path = write_lines(tmp_path / "f.ndjson", ["", json.dumps(record), "   "])
        assert len(read_rows(path, "f")) == 1

    def test_bad_json_reports_line_number(self, tmp_path, record):
        path = write_lines(tmp_path / "f.ndjson", [json.dumps(record), "{not json"])
        with pytest.raises(LoadError, match="f line 2"):
            read_rows(path, "f")

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda r: r.pop("snapshot_time"),
            lambda r: r.update(snapshot_time="123"),
            lambda r: r.update(snapshot_time=True),
            lambda r: r.pop("icao24"),
            lambda r: r.update(latitude=500),
            lambda r: r.update(on_ground=None),
        ],
        ids=["no-snapshot-time", "string-time", "bool-time", "no-icao24", "bad-latitude", "null-on-ground"],
    )
    def test_invalid_record_raises(self, tmp_path, record, mutate):
        mutate(record)
        path = write_lines(tmp_path / "f.ndjson", [json.dumps(record)])
        with pytest.raises(LoadError, match="line 1"):
            read_rows(path, "f")

    @pytest.mark.parametrize("line", ["[]", "42", "null", '"text"'])
    def test_non_object_line_raises(self, tmp_path, line):
        with pytest.raises(LoadError):
            read_rows(write_lines(tmp_path / "f.ndjson", [line]), "f")


def test_load_result_rows_total():
    assert LoadResult(loaded={"a": 2, "b": 3}).rows == 5
    assert LoadResult().rows == 0
