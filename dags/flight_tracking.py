"""
### Flight tracking pipeline

Every 5 minutes:

1. **extract**: fetch live aircraft positions from OpenSky and write an NDJSON file to `data/raw/`
2. **load**: copy any new raw files into `raw.flight_states` in the warehouse
3. **dbt_build**: rebuild the staging and mart models and run all dbt tests

The OpenSky area is set with `OPENSKY_BBOX`. Keep it small when running without
credentials: anonymous access allows about 400 small-area requests per day.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag, task

DBT_BIN = os.environ.get("DBT_BIN", "/home/airflow/dbt-venv/bin/dbt")
DBT_PROJECT_DIR = os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt")

DEFAULT_ARGS = {
    "owner": "flights",
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
    "execution_timeout": timedelta(minutes=10),
}


def run_step(name: str, main: Callable[[list[str]], int]) -> None:
    """Run a CLI entry point and fail the task if it exits non-zero."""
    code = main([])
    if code != 0:
        raise RuntimeError(f"{name} exited with code {code}; see the log above for details")


@dag(
    dag_id="flight_tracking",
    schedule="*/5 * * * *",
    start_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
    catchup=False,  # OpenSky only serves live data, so there's nothing to backfill
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["flights"],
    doc_md=__doc__,
)
def flight_tracking():
    @task
    def extract() -> None:
        from extract.run import main  # imported here to keep DAG parsing fast

        run_step("extract", main)

    @task
    def load() -> None:
        from load.run import main

        run_step("load", main)

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=(
            f"{DBT_BIN} build --project-dir {DBT_PROJECT_DIR} --profiles-dir {DBT_PROJECT_DIR} "
            "--target-path /tmp/dbt/target --log-path /tmp/dbt/logs"
        ),
        retries=0,  # a failing dbt test won't fix itself; don't hide it behind retries
    )

    extract() >> load() >> dbt_build


flight_tracking()
