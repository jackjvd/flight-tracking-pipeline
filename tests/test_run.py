import json
import logging
from unittest.mock import MagicMock

from extract.config import BoundingBox
from extract.models import StatesSnapshot
from extract.opensky_client import OpenSkyError
from extract.run import EXIT_API_ERROR, EXIT_CONFIG_ERROR, EXIT_OK, main


def fake_client(snapshot=None, error=None):
    client = MagicMock()
    if error:
        client.get_states.side_effect = error
    else:
        client.get_states.return_value = snapshot
    return client


def test_success_writes_file(tmp_path, api_payload):
    client = fake_client(StatesSnapshot.from_api(api_payload))
    assert main(["--output-dir", str(tmp_path)], client=client) == EXIT_OK
    files = list(tmp_path.rglob("*.ndjson"))
    assert len(files) == 1
    assert len(files[0].read_text().splitlines()) == 2


def test_uses_output_dir_from_env(tmp_path, monkeypatch, api_payload):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "envdir"))
    main([], client=fake_client(StatesSnapshot.from_api(api_payload)))
    assert list((tmp_path / "envdir").rglob("*.ndjson"))


def test_cli_bbox_overrides_env(tmp_path, monkeypatch, api_payload):
    monkeypatch.setenv("OPENSKY_BBOX", "1,2,3,4")
    client = fake_client(StatesSnapshot.from_api(api_payload))
    main(["--bbox", "10,20,30,40", "--output-dir", str(tmp_path)], client=client)
    client.get_states.assert_called_once_with(BoundingBox(10, 20, 30, 40))


def test_env_bbox_used_without_cli_flag(tmp_path, monkeypatch, api_payload):
    monkeypatch.setenv("OPENSKY_BBOX", "1,2,3,4")
    client = fake_client(StatesSnapshot.from_api(api_payload))
    main(["--output-dir", str(tmp_path)], client=client)
    client.get_states.assert_called_once_with(BoundingBox(1, 2, 3, 4))


def test_invalid_cli_bbox_is_config_error(tmp_path, caplog):
    client = fake_client()
    assert main(["--bbox", "nonsense"], client=client) == EXIT_CONFIG_ERROR
    client.get_states.assert_not_called()
    assert "Configuration error" in caplog.text


def test_half_credentials_is_config_error(monkeypatch):
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "only-id")
    assert main([], client=fake_client()) == EXIT_CONFIG_ERROR


def test_api_error_returns_nonzero_and_writes_nothing(tmp_path, caplog):
    client = fake_client(error=OpenSkyError("HTTP 503"))
    assert main(["--output-dir", str(tmp_path)], client=client) == EXIT_API_ERROR
    assert not list(tmp_path.rglob("*.ndjson"))
    assert "Extract failed" in caplog.text


def test_logs_skipped_count(tmp_path, api_payload, caplog):
    caplog.set_level(logging.INFO)
    api_payload["states"].append(["bad"])
    main(["--output-dir", str(tmp_path)], client=fake_client(StatesSnapshot.from_api(api_payload)))
    assert "Wrote 2 states (1 skipped)" in caplog.text


def test_output_records_are_valid_json(tmp_path, api_payload):
    main(["--output-dir", str(tmp_path)], client=fake_client(StatesSnapshot.from_api(api_payload)))
    (path,) = tmp_path.rglob("*.ndjson")
    for line in path.read_text().splitlines():
        assert json.loads(line)["snapshot_time"] == api_payload["time"]
