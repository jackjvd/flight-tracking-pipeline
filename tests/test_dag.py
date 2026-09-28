"""Checks on the Airflow DAG. Skipped when Airflow isn't installed (see `make setup`)."""

import os
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

# Keep Airflow from writing config/logs into ~/airflow during tests.
os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="airflow-test-"))
os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "false")
os.environ.setdefault("AIRFLOW__CORE__UNIT_TEST_MODE", "true")

pytest.importorskip("airflow")
from airflow.dag_processing.dagbag import DagBag  # noqa: E402

DAGS_DIR = Path(__file__).resolve().parents[1] / "dags"


@pytest.fixture(scope="module")
def dagbag():
    return DagBag(dag_folder=str(DAGS_DIR))


@pytest.fixture(scope="module")
def dag(dagbag):
    return dagbag.dags.get("flight_tracking")


def test_no_import_errors(dagbag):
    assert dagbag.import_errors == {}


def test_dag_is_registered(dag):
    assert dag is not None


def test_schedule_and_run_settings(dag):
    assert dag.schedule == "*/5 * * * *"
    assert dag.catchup is False
    assert dag.max_active_runs == 1
    assert dag.start_date.tzinfo is not None
    assert "flights" in dag.tags
    assert dag.doc_md


def test_task_order(dag):
    assert set(dag.task_ids) == {"extract", "load", "dbt_build"}
    assert dag.get_task("extract").downstream_task_ids == {"load"}
    assert dag.get_task("load").downstream_task_ids == {"dbt_build"}
    assert dag.get_task("dbt_build").downstream_task_ids == set()


def test_retries_and_timeouts(dag):
    for task_id in ("extract", "load"):
        task = dag.get_task(task_id)
        assert task.retries == 2
        assert task.retry_delay == timedelta(minutes=1)
    for task in dag.tasks:
        assert task.execution_timeout == timedelta(minutes=10)
    assert dag.get_task("dbt_build").retries == 0


def test_dbt_command(dag):
    command = dag.get_task("dbt_build").bash_command
    assert " build " in command
    assert "--project-dir /opt/airflow/dbt" in command
    assert "--profiles-dir /opt/airflow/dbt" in command
    assert "--target-path /tmp/dbt/target" in command


@pytest.mark.parametrize("task_id, module", [("extract", "extract.run"), ("load", "load.run")])
def test_task_calls_cli_entry_point(dag, monkeypatch, task_id, module):
    calls = []
    monkeypatch.setattr(f"{module}.main", lambda argv: calls.append(argv) or 0)
    dag.get_task(task_id).python_callable()
    assert calls == [[]]


@pytest.mark.parametrize("task_id, module", [("extract", "extract.run"), ("load", "load.run")])
@pytest.mark.parametrize("code", [1, 2])
def test_task_fails_on_nonzero_exit(dag, monkeypatch, task_id, module, code):
    monkeypatch.setattr(f"{module}.main", lambda argv: code)
    with pytest.raises(RuntimeError, match=f"{task_id} exited with code {code}"):
        dag.get_task(task_id).python_callable()
