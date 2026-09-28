import logging

import pytest

from load.run import EXIT_CONFIG_ERROR, EXIT_LOAD_ERROR, EXIT_OK, main


def test_missing_warehouse_url_is_config_error(caplog):
    assert main([]) == EXIT_CONFIG_ERROR
    assert "WAREHOUSE_URL is not set" in caplog.text


def test_unreachable_database(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("WAREHOUSE_URL", "postgresql://nobody:x@127.0.0.1:1/none")
    assert main(["--input-dir", str(tmp_path)]) == EXIT_LOAD_ERROR
    assert "Database error" in caplog.text


def test_reads_warehouse_url_from_dotenv(tmp_path, caplog):
    (tmp_path / ".env").write_text("WAREHOUSE_URL=postgresql://nobody:x@127.0.0.1:1/none\n")
    assert main(["--input-dir", str(tmp_path)]) == EXIT_LOAD_ERROR  # got past config check


@pytest.mark.integration
def test_end_to_end(db, warehouse_url, monkeypatch, raw_dir, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("WAREHOUSE_URL", warehouse_url)
    assert main(["--input-dir", str(raw_dir)]) == EXIT_OK
    assert "Loaded 2 rows from 1 files, 0 failed" in caplog.text
    assert db.execute("SELECT count(*) FROM raw.flight_states").fetchone()[0] == 2


@pytest.mark.integration
def test_uses_output_dir_env_as_default(db, warehouse_url, monkeypatch, raw_dir):
    monkeypatch.setenv("WAREHOUSE_URL", warehouse_url)
    monkeypatch.setenv("OUTPUT_DIR", str(raw_dir))
    assert main([]) == EXIT_OK
    assert db.execute("SELECT count(*) FROM raw.flight_states").fetchone()[0] == 2


@pytest.mark.integration
def test_bad_file_gives_nonzero_exit(db, warehouse_url, monkeypatch, raw_dir):
    monkeypatch.setenv("WAREHOUSE_URL", warehouse_url)
    (path,) = raw_dir.rglob("*.ndjson")
    path.write_text("{broken\n")
    assert main(["--input-dir", str(raw_dir)]) == EXIT_LOAD_ERROR
