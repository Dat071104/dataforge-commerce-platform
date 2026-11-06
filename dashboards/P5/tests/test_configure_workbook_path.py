"""Offline safety tests for the local PBIP workbook configuration helper."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from configure_workbook_path import ConfigurationError, configure_workbook_path  # noqa: E402


def _make_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "DataForge"
    expressions = project / "DataForge.SemanticModel" / "definition" / "expressions.tmdl"
    expressions.parent.mkdir(parents=True)
    (project / "DataForge.pbip").write_text("{}\n", encoding="utf-8")
    expressions.write_text(
        'expression GoldWorkbookPath = "__DATAFORGE_LOCAL_WORKBOOK_PATH__" '
        'meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
        'expression GoldWorkbook = Excel.Workbook(File.Contents(GoldWorkbookPath), null, true)\n',
        encoding="utf-8",
    )
    return project, expressions


def _make_export(folder: Path, *, expected_rows: int = 2) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "fct_order_item"
    sheet.append(["order_id", "amount"])
    sheet.append(["A", 100])
    sheet.append(["B", 200])
    workbook_path = folder / "DataForgeGold.xlsx"
    workbook.save(workbook_path)
    workbook.close()

    digest = hashlib.sha256(workbook_path.read_bytes()).hexdigest()
    manifest = {
        "data_classification": "synthetic demo",
        "tables": [{"table": "fct_order_item", "row_count": expected_rows}],
        "excel_workbook": {
            "file": workbook_path.name,
            "sha256": digest,
            "sheets": ["fct_order_item"],
        },
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return workbook_path


def test_configure_validates_manifest_and_writes_atomic_parameter_with_backup(tmp_path):
    project, expressions = _make_project(tmp_path)
    original = expressions.read_bytes()
    workbook = _make_export(tmp_path / "portable" / "data" / "powerbi_gold_export")
    backup_dir = tmp_path / "backups"

    configured, backup = configure_workbook_path(
        project / "DataForge.pbip", workbook, backup_dir=backup_dir
    )

    assert configured == expressions
    assert backup is not None and backup.is_file()
    assert backup.read_bytes() == original
    assert str(workbook.resolve()) in expressions.read_text(encoding="utf-8")
    assert "__DATAFORGE_LOCAL_WORKBOOK_PATH__" not in expressions.read_text(encoding="utf-8")


def test_rejects_workbook_digest_mismatch_without_touching_project(tmp_path):
    project, expressions = _make_project(tmp_path)
    original = expressions.read_bytes()
    workbook = _make_export(tmp_path / "export")
    with workbook.open("ab") as stream:
        stream.write(b"tampered")

    with pytest.raises(ConfigurationError, match="SHA-256"):
        configure_workbook_path(project, workbook, backup_dir=tmp_path / "backups")

    assert expressions.read_bytes() == original
    assert not (tmp_path / "backups").exists()


def test_rejects_workbook_row_count_mismatch_without_touching_project(tmp_path):
    project, expressions = _make_project(tmp_path)
    original = expressions.read_bytes()
    workbook = _make_export(tmp_path / "export", expected_rows=3)

    with pytest.raises(ConfigurationError, match="row count mismatch"):
        configure_workbook_path(project, workbook, backup_dir=tmp_path / "backups")

    assert expressions.read_bytes() == original
    assert not (tmp_path / "backups").exists()


def test_configure_dry_run_validates_without_creating_backup_or_editing(tmp_path):
    project, expressions = _make_project(tmp_path)
    original = expressions.read_bytes()
    workbook = _make_export(tmp_path / "export")

    configured, backup = configure_workbook_path(project, workbook, dry_run=True)

    assert configured == expressions
    assert backup is None
    assert expressions.read_bytes() == original
    assert not (tmp_path / ".pbi-workbook-path-backups").exists()
