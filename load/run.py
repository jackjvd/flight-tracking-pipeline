"""Command-line entry point: load pending raw snapshots into the warehouse.

    python -m load.run [--input-dir DIR]
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import psycopg
from dotenv import find_dotenv, load_dotenv

from load.loader import load_pending

log = logging.getLogger("load")

EXIT_OK = 0
EXIT_LOAD_ERROR = 1
EXIT_CONFIG_ERROR = 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input-dir", type=Path, help="raw data folder (default: OUTPUT_DIR)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    load_dotenv(find_dotenv(usecwd=True))
    url = os.environ.get("WAREHOUSE_URL", "").strip()
    if not url:
        log.error("Configuration error: WAREHOUSE_URL is not set")
        return EXIT_CONFIG_ERROR
    input_dir = args.input_dir or Path(os.environ.get("OUTPUT_DIR", "").strip() or "data/raw")

    try:
        with psycopg.connect(url, autocommit=True, connect_timeout=10) as conn:
            result = load_pending(conn, input_dir)
    except psycopg.Error as exc:
        log.error("Database error: %s", exc)
        return EXIT_LOAD_ERROR

    log.info("Loaded %d rows from %d files, %d failed", result.rows, len(result.loaded), len(result.failed))
    return EXIT_LOAD_ERROR if result.failed else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
