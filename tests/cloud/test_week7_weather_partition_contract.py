from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_mini3_weather_orchestrators_pass_one_partition_date():
    staging_model = (
        REPO_ROOT
        / "dbt"
        / "dataforge"
        / "models"
        / "weather"
        / "staging"
        / "stg_weather_mini3_landing.sql"
    ).read_text(encoding="utf-8")
    workflow = (
        REPO_ROOT / "cloud" / "workflows" / "week7_weather_workflow.yaml"
    ).read_text(encoding="utf-8")
    airflow = (
        REPO_ROOT
        / "labs"
        / "airflow_reference"
        / "dags"
        / "dataforge_week7_weather_cloud.py"
    ).read_text(encoding="utf-8")
    publication_macro = (
        REPO_ROOT
        / "dbt"
        / "dataforge"
        / "macros"
        / "weather_mini3_publication.sql"
    ).read_text(encoding="utf-8")
    terraform = (
        REPO_ROOT / "cloud" / "terraform" / "dev" / "week7_weather.tf"
    ).read_text(encoding="utf-8")

    assert "where observation_date = date('{{ weather_observation_date }}')" in staging_model
    assert "weather_observation_date: ${observation_date}" in workflow
    assert workflow.count('"--vars"') >= 2
    assert airflow.count('"--vars"') >= 2
    assert 'weather_dbt_vars_argument(request["observation_date"])' in airflow
    assert "observation_date >= DATE '1940-01-01'" in publication_macro
    assert "CAST(NULL AS STRING) AS batch_key" in publication_macro
    assert "CAST(NULL AS STRING) AS request_id" not in publication_macro
    assert 'table_id            = "published_weather_daily"' in terraform
    assert '"week7_weather_workflow_published_view_reader"' in terraform
    assert '"week7_weather_workflow_versions_reader"' in terraform
