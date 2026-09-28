from pathlib import Path

import pytest

from extract.config import BoundingBox, ConfigError, Settings


class TestBoundingBox:
    def test_parse_valid(self):
        box = BoundingBox.parse("45.8, 5.9, 47.8, 10.5")
        assert box == BoundingBox(45.8, 5.9, 47.8, 10.5)

    def test_as_params(self):
        assert BoundingBox(1, 2, 3, 4).as_params() == {"lamin": 1, "lomin": 2, "lamax": 3, "lomax": 4}

    def test_accepts_extreme_edges(self):
        BoundingBox(-90, -180, 90, 180)

    @pytest.mark.parametrize("raw", ["", "1,2,3", "1,2,3,4,5"])
    def test_parse_wrong_count(self, raw):
        with pytest.raises(ConfigError, match="4 comma-separated"):
            BoundingBox.parse(raw)

    def test_parse_non_numeric(self):
        with pytest.raises(ConfigError, match="must be numbers"):
            BoundingBox.parse("a,2,3,4")

    @pytest.mark.parametrize(
        "args, message",
        [
            ((-91, 0, 10, 10), "lamin"),
            ((0, 0, 91, 10), "lamax"),
            ((0, -181, 10, 10), "lomin"),
            ((0, 0, 10, 181), "lomax"),
            ((10, 0, 10, 10), "lamin must be less than lamax"),
            ((20, 0, 10, 10), "lamin must be less than lamax"),
            ((0, 10, 10, 10), "lomin must be less than lomax"),
        ],
    )
    def test_rejects_invalid_ranges(self, args, message):
        with pytest.raises(ConfigError, match=message):
            BoundingBox(*args)


class TestSettings:
    def test_defaults_from_empty_env(self):
        settings = Settings.from_env({})
        assert settings.client_id is None
        assert settings.client_secret is None
        assert settings.bbox is None
        assert settings.output_dir == Path("data/raw")
        assert not settings.has_credentials

    def test_full_env(self):
        settings = Settings.from_env(
            {
                "OPENSKY_CLIENT_ID": " id ",
                "OPENSKY_CLIENT_SECRET": "secret",
                "OPENSKY_BBOX": "45.8,5.9,47.8,10.5",
                "OUTPUT_DIR": "/tmp/out",
            }
        )
        assert settings.client_id == "id"
        assert settings.has_credentials
        assert settings.bbox == BoundingBox(45.8, 5.9, 47.8, 10.5)
        assert settings.output_dir == Path("/tmp/out")

    def test_blank_values_treated_as_unset(self):
        settings = Settings.from_env(
            {"OPENSKY_CLIENT_ID": "  ", "OPENSKY_CLIENT_SECRET": "", "OPENSKY_BBOX": " ", "OUTPUT_DIR": ""}
        )
        assert not settings.has_credentials
        assert settings.bbox is None
        assert settings.output_dir == Path("data/raw")

    @pytest.mark.parametrize(
        "env", [{"OPENSKY_CLIENT_ID": "id"}, {"OPENSKY_CLIENT_SECRET": "secret"}]
    )
    def test_half_credentials_rejected(self, env):
        with pytest.raises(ConfigError, match="both"):
            Settings.from_env(env)

    def test_invalid_bbox_in_env_rejected(self):
        with pytest.raises(ConfigError):
            Settings.from_env({"OPENSKY_BBOX": "1,2,3"})

    def test_reads_os_environ(self, monkeypatch):
        monkeypatch.setenv("OPENSKY_BBOX", "1,2,3,4")
        assert Settings.from_env().bbox == BoundingBox(1, 2, 3, 4)

    def test_reads_dotenv_file(self, tmp_path):
        (tmp_path / ".env").write_text("OUTPUT_DIR=from_dotenv\n")
        assert Settings.from_env().output_dir == Path("from_dotenv")

    def test_os_environ_beats_dotenv(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("OUTPUT_DIR=from_dotenv\n")
        monkeypatch.setenv("OUTPUT_DIR", "from_env")
        assert Settings.from_env().output_dir == Path("from_env")
