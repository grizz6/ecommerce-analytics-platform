# Astro Runtime 3.3-12: Apache Airflow 3.3.2 on Python 3.12, matching the
# rest of the project.
FROM astrocrpublic.azurecr.io/runtime:3.3-12-python-3.12

# dbt and the extract/load code each get their own virtual environment, so
# their pinned versions never change the packages Airflow itself depends on.
# The pins match pyproject.toml; tests/test_orchestration_pins.py keeps them
# in step.
COPY include/requirements-dbt.txt include/requirements-extract-load.txt /tmp/
RUN python -m venv /usr/local/airflow/dbt_venv \
    && /usr/local/airflow/dbt_venv/bin/pip install --no-cache-dir -r /tmp/requirements-dbt.txt \
    && python -m venv /usr/local/airflow/el_venv \
    && /usr/local/airflow/el_venv/bin/pip install --no-cache-dir -r /tmp/requirements-extract-load.txt
