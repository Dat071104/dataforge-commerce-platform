from pathlib import Path

MACRO = Path(__file__).parents[1] / "macros" / "weather_mini3_publication.sql"


def test_empty_weather_pointer_is_initialized_before_publication_transaction():
    sql = MACRO.read_text(encoding="utf-8")

    assert "SET v_pointer_rows = (SELECT COUNT(*) FROM {{ pointer }})" in sql
    assert "ASSERT v_pointer_rows <= 1" in sql
    assert "IF v_pointer_rows = 0 THEN" in sql
    assert "MERGE {{ pointer }} AS current_pointer" in sql
    assert "WHEN NOT MATCHED THEN" in sql
    assert "VALUES (\n                      seed.singleton_id,\n                      0," in sql
    assert "                      FALSE,\n                      CURRENT_TIMESTAMP()" in sql
    assert sql.index("MERGE {{ pointer }} AS current_pointer") < sql.index(
        "BEGIN TRANSACTION;\n            SET v_prior_version"
    )


def test_duplicate_or_malformed_weather_pointer_fails_closed():
    sql = MACRO.read_text(encoding="utf-8")

    assert "ASSERT v_pointer_rows <= 1" in sql
    assert "ASSERT v_pointer_rows = 1" in sql
    assert "(SELECT COUNTIF(singleton_id = 1) FROM {{ pointer }}) = 1" in sql
