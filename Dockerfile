# Keep this Airflow version in sync with AIRFLOW_VERSION in the Makefile.
FROM apache/airflow:3.3.2-python3.14

COPY --chmod=644 requirements.txt requirements-dbt.txt /

# Pin apache-airflow alongside our requirements so pip can't change its version.
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /requirements.txt

# dbt gets its own virtualenv: its dependencies conflict with Airflow's.
RUN python -m venv /home/airflow/dbt-venv \
    && /home/airflow/dbt-venv/bin/pip install --no-cache-dir -r /requirements-dbt.txt
