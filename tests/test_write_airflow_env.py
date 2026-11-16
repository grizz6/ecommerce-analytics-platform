import json
import stat
from pathlib import Path

import pytest

from scripts import write_airflow_env as wae

ACCOUNT = "ABCDEFG-XY12345"
LOADER_PASS = "loader pass #1"
DBT_PASS = 'dbt"pass\\2'


def _answers(*values: str):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def test_build_env_points_at_container_mounts() -> None:
    env = wae.build_env("my-project", ACCOUNT, LOADER_PASS, DBT_PASS)
    assert env["RAW_DATA_DIR"] == "/usr/local/airflow/project/data/raw/ga4"
    assert env["SNOWFLAKE_LOADER_PRIVATE_KEY_PATH"] == "/usr/local/airflow/keys/loader_svc.p8"
    assert env["GOOGLE_APPLICATION_CREDENTIALS"] == "/usr/local/airflow/gcloud/adc.json"
    connection = json.loads(env["AIRFLOW_CONN_SNOWFLAKE_DBT"])
    assert connection["login"] == "DBT_SVC"
    assert connection["password"] == DBT_PASS
    assert connection["extra"]["private_key_file"] == "/usr/local/airflow/keys/dbt_svc.p8"
    assert connection["extra"]["role"] == "TRANSFORMER"


@pytest.mark.parametrize(
    ("account", "loader", "dbt", "message"),
    [
        ("org.account", LOADER_PASS, DBT_PASS, "ORGNAME-ACCOUNTNAME"),
        (ACCOUNT, "", DBT_PASS, "cannot be empty"),
        (ACCOUNT, LOADER_PASS, "it's", "single quote"),
        (ACCOUNT, "two\nlines", DBT_PASS, "line break"),
    ],
)
def test_build_env_rejects_unsafe_values(account: str, loader: str, dbt: str, message: str) -> None:
    with pytest.raises(wae.EnvFileError, match=message):
        wae.build_env("my-project", account, loader, dbt)


def test_main_writes_owner_only_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "orchestration" / ".env"
    code = wae.main(
        ["--output", str(output)],
        prompt=_answers(ACCOUNT, LOADER_PASS, DBT_PASS),
        project_reader=lambda: "my-project",
    )
    assert code == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    content = output.read_text()
    assert f"SNOWFLAKE_LOADER_PRIVATE_KEY_PASSPHRASE='{LOADER_PASS}'" in content
    assert "GCP_PROJECT_ID='my-project'" in content
    logged = capsys.readouterr().err
    for secret in (ACCOUNT, LOADER_PASS, DBT_PASS, "my-project"):
        assert secret not in logged


def test_main_refuses_bad_input_and_writes_nothing(tmp_path: Path) -> None:
    output = tmp_path / ".env"
    code = wae.main(
        ["--output", str(output)],
        prompt=_answers("not an account", LOADER_PASS, DBT_PASS),
        project_reader=lambda: "my-project",
    )
    assert code == 1
    assert not output.exists()


def test_gcloud_failure_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("gcloud")

    monkeypatch.setattr(wae.subprocess, "run", missing)
    with pytest.raises(wae.EnvFileError, match="gcloud config set project"):
        wae.gcloud_project()
