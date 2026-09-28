"""Write snapshots to the raw landing zone as newline-delimited JSON."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from extract.models import StatesSnapshot


def snapshot_path(output_dir: Path, snapshot_time: int) -> Path:
    day = datetime.fromtimestamp(snapshot_time, UTC).strftime("%Y-%m-%d")
    return Path(output_dir) / "states" / f"date={day}" / f"states_{snapshot_time}.ndjson"


def write_snapshot(snapshot: StatesSnapshot, output_dir: Path) -> Path:
    """Write one row per aircraft and return the file path.

    The file name is keyed on the snapshot time, so re-running for the same
    snapshot overwrites instead of duplicating. An empty snapshot still produces
    an (empty) file as a record that the poll happened.
    """
    path = snapshot_path(output_dir, snapshot.time)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file and rename, so readers never see a half-written file.
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for state in snapshot.states:
                record = {"snapshot_time": snapshot.time, **state.model_dump()}
                f.write(json.dumps(record) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path
