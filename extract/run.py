"""Command-line entry point: fetch one snapshot from OpenSky and write it to disk.

    python -m extract.run [--bbox LAMIN,LOMIN,LAMAX,LOMAX] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import replace
from pathlib import Path

from extract.config import BoundingBox, ConfigError, Settings
from extract.opensky_client import OpenSkyClient, OpenSkyError
from extract.writer import write_snapshot

log = logging.getLogger("extract")

EXIT_OK = 0
EXIT_API_ERROR = 1
EXIT_CONFIG_ERROR = 2


def main(argv: list[str] | None = None, client: OpenSkyClient | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bbox", help="lamin,lomin,lamax,lomax (overrides OPENSKY_BBOX)")
    parser.add_argument("--output-dir", type=Path, help="overrides OUTPUT_DIR")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        settings = Settings.from_env()
        if args.bbox:
            settings = replace(settings, bbox=BoundingBox.parse(args.bbox))
        if args.output_dir:
            settings = replace(settings, output_dir=args.output_dir)
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        return EXIT_CONFIG_ERROR

    client = client or OpenSkyClient(settings)
    try:
        snapshot = client.get_states(settings.bbox)
    except OpenSkyError as exc:
        log.error("Extract failed: %s", exc)
        return EXIT_API_ERROR

    path = write_snapshot(snapshot, settings.output_dir)
    log.info("Wrote %d states (%d skipped) to %s", len(snapshot.states), snapshot.skipped, path)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
