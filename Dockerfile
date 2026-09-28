FROM apache/airflow:3.3.2-python3.14

# Pin apache-airflow alongside our requirements so pip can't change its version.
COPY --chmod=644 requirements.txt /requirements.txt
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /requirements.txt
