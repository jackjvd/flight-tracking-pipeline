import pytest
from pydantic import ValidationError

from extract.models import StatesSnapshot, StateVector


class TestStateVector:
    def test_parses_valid_row(self, valid_row):
        state = StateVector.from_row(valid_row)
        assert state.icao24 == "4b1805"
        assert state.callsign == "SWR123"  # trailing padding stripped
        assert state.origin_country == "Switzerland"
        assert state.latitude == pytest.approx(47.4581)
        assert state.on_ground is False
        assert state.category is None

    def test_parses_extended_row_with_category(self, valid_row):
        state = StateVector.from_row(valid_row + [4])
        assert state.category == 4

    def test_icao24_normalized_to_lowercase(self, valid_row):
        valid_row[0] = " 4B1805 "
        assert StateVector.from_row(valid_row).icao24 == "4b1805"

    @pytest.mark.parametrize("callsign", ["", "   ", None])
    def test_blank_callsign_becomes_none(self, valid_row, callsign):
        valid_row[1] = callsign
        assert StateVector.from_row(valid_row).callsign is None

    def test_nullable_position_fields(self, valid_row):
        # Aircraft without a position fix send nulls for these.
        for i in (3, 5, 6, 7, 9, 10, 11, 13, 14):
            valid_row[i] = None
        state = StateVector.from_row(valid_row)
        assert state.latitude is None and state.longitude is None and state.squawk is None

    def test_sensors_list(self, valid_row):
        valid_row[12] = [1, 2, 3]
        assert StateVector.from_row(valid_row).sensors == [1, 2, 3]

    @pytest.mark.parametrize("row", [[], ["4b1805"] * 16, "not a list", None])
    def test_rejects_short_or_non_list_rows(self, row):
        with pytest.raises(ValueError, match="at least 17"):
            StateVector.from_row(row)

    @pytest.mark.parametrize(
        "index, value",
        [
            (0, "zzzzzz"),  # icao24 not hex
            (0, "4b18"),  # icao24 too short
            (0, None),
            (2, None),  # origin_country required
            (4, None),  # last_contact required
            (5, 181.0),  # longitude out of range
            (6, -90.5),  # latitude out of range
            (8, None),  # on_ground required
            (9, -1.0),  # negative velocity
            (16, 4),  # position_source out of 0-3
            (4, "not-a-timestamp"),
        ],
    )
    def test_rejects_invalid_values(self, valid_row, index, value):
        valid_row[index] = value
        with pytest.raises(ValidationError):
            StateVector.from_row(valid_row)


class TestStatesSnapshot:
    def test_parses_payload(self, api_payload):
        snapshot = StatesSnapshot.from_api(api_payload)
        assert snapshot.time == 1727366405
        assert [s.icao24 for s in snapshot.states] == ["4b1805", "a1b2c3"]
        assert snapshot.skipped == 0

    @pytest.mark.parametrize("states", [None, []])
    def test_null_or_empty_states(self, states):
        snapshot = StatesSnapshot.from_api({"time": 1, "states": states})
        assert snapshot.states == []
        assert snapshot.skipped == 0

    def test_missing_states_key(self):
        assert StatesSnapshot.from_api({"time": 1}).states == []

    def test_skips_and_counts_bad_rows(self, api_payload, caplog):
        bad_value = list(api_payload["states"][0])
        bad_value[6] = 200.0
        api_payload["states"] += [bad_value, ["too", "short"], None]
        snapshot = StatesSnapshot.from_api(api_payload)
        assert len(snapshot.states) == 2
        assert snapshot.skipped == 3
        assert "Skipping malformed state row" in caplog.text

    @pytest.mark.parametrize("payload", [{}, {"time": None}, {"time": "123"}, [], None])
    def test_rejects_payload_without_time(self, payload):
        with pytest.raises(ValueError, match="time"):
            StatesSnapshot.from_api(payload)
