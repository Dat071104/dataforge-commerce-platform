"""Validate a local Gold export and configure the PBIP workbook path safely."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """Raised when the requested workbook or PBIP parameter is unsafe to use."""


def _resolve_project_dir(project_arg: Path) -> Path:
    project_path = project_arg.expanduser().resolve(strict=True)
    if project_path.is_file():
        if project_path.suffix.casefold() != ".pbip":
            raise ConfigurationError(f"expected a .pbip file or project directory: {project_path}")
        project_dir = project_path.parent
    elif project_path.is_dir():
        candidates = sorted(project_path.glob("*.pbip"))
        if len(candidates) != 1:
            raise ConfigurationError(
                f"expected exactly one .pbip file in {project_path}; found {len(candidates)}"
            )
        project_dir = project_path
    else:
        raise ConfigurationError(f"PBIP project does not exist: {project_path}")

    model_dir = project_dir / "DataForge.SemanticModel" / "definition"
    if not (model_dir / "expressions.tmdl").is_file():
        raise ConfigurationError(f"missing semantic model expressions file: {model_dir}")
    return project_dir


def _load_manifest(workbook: Path) -> tuple[dict[str, Any], Path]:
    manifest_path = workbook.parent / "manifest.json"
    if not manifest_path.is_file():
        raise ConfigurationError(
            f"missing sibling manifest: {manifest_path}; use the complete Gold export folder"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"cannot read Gold export manifest: {manifest_path}") from exc
    if not isinstance(manifest, dict):
        raise ConfigurationError("Gold export manifest must contain a JSON object")
    if "synthetic" not in str(manifest.get("data_classification", "")).casefold():
        raise ConfigurationError("Gold export manifest is not marked synthetic")
    return manifest, manifest_path


def validate_workbook(workbook_arg: Path) -> Path:
    """Validate the workbook's synthetic marker, digest, sheets, and row counts."""
    workbook = workbook_arg.expanduser().resolve(strict=True)
    if not workbook.is_file() or workbook.suffix.casefold() != ".xlsx":
        raise ConfigurationError(f"expected an existing .xlsx workbook: {workbook}")

    manifest, _ = _load_manifest(workbook)
    workbook_meta = manifest.get("excel_workbook")
    if not isinstance(workbook_meta, dict) or workbook_meta.get("file") != workbook.name:
        raise ConfigurationError("manifest workbook filename does not match the selected workbook")
    expected_digest = workbook_meta.get("sha256")
    actual_digest = hashlib.sha256(workbook.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        raise ConfigurationError("workbook SHA-256 does not match the sibling manifest")

    expected_sheets = workbook_meta.get("sheets")
    tables = manifest.get("tables")
    if not isinstance(expected_sheets, list) or not isinstance(tables, list):
        raise ConfigurationError("manifest must list workbook sheets and exported tables")
    row_counts: dict[str, int] = {}
    for item in tables:
        if not isinstance(item, dict) or not isinstance(item.get("table"), str):
            raise ConfigurationError("manifest contains an invalid table entry")
        count = item.get("row_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ConfigurationError(f"invalid row_count for table {item.get('table')!r}")
        row_counts[item["table"]] = count
    if len(row_counts) != len(tables) or set(row_counts) != set(expected_sheets):
        raise ConfigurationError("manifest sheet names and table entries do not match")

    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - install failure is environment-specific
        raise ConfigurationError("install the optional Power BI dependencies: pip install -e '.[powerbi]'") from exc

    try:
        book = load_workbook(workbook, read_only=True, data_only=True)
        try:
            if book.sheetnames != expected_sheets:
                raise ConfigurationError("workbook sheets do not match the sibling manifest")
            for sheet in book.worksheets:
                iterator = sheet.iter_rows(values_only=True)
                next(iterator, None)  # header row
                actual_rows = sum(1 for row in iterator if any(value is not None for value in row))
                expected_rows = row_counts[sheet.title]
                if actual_rows != expected_rows:
                    raise ConfigurationError(
                        f"workbook row count mismatch for {sheet.title}: "
                        f"expected {expected_rows}, found {actual_rows}"
                    )
        finally:
            book.close()
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(f"cannot read workbook {workbook}: {exc}") from exc
    return workbook


_PARAMETER_LINE = re.compile(
    r'(?m)^(expression GoldWorkbookPath = )("(?:[^"]|"")*")'
    r'( meta \[IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true\])(\r?)$'
)


def _unquote_m_string(literal: str) -> str:
    if len(literal) < 2 or not (literal.startswith('"') and literal.endswith('"')):
        raise ConfigurationError("GoldWorkbookPath must be a quoted Power Query text value")
    return literal[1:-1].replace('""', '"')


def _quote_m_string(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise ConfigurationError("workbook path cannot contain line breaks")
    return '"' + value.replace('"', '""') + '"'


def configure_workbook_path(
    project_arg: Path,
    workbook_arg: Path,
    *,
    backup_dir: Path | None = None,
    dry_run: bool = False,
) -> tuple[Path, Path | None]:
    """Set the workbook parameter after validation, preserving a timestamped backup."""
    project_dir = _resolve_project_dir(project_arg)
    workbook = validate_workbook(workbook_arg)
    expressions = project_dir / "DataForge.SemanticModel" / "definition" / "expressions.tmdl"
    original_bytes = expressions.read_bytes()
    try:
        original_text = original_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigurationError(f"expressions file is not UTF-8: {expressions}") from exc
    matches = list(_PARAMETER_LINE.finditer(original_text))
    if len(matches) != 1:
        raise ConfigurationError(
            f"expected one GoldWorkbookPath parameter in {expressions}; found {len(matches)}"
        )
    current = _unquote_m_string(matches[0].group(2))
    target = str(workbook)
    if os.path.normcase(os.path.abspath(current)) == os.path.normcase(target):
        return expressions, None

    replacement = (
        matches[0].group(1)
        + _quote_m_string(target)
        + matches[0].group(3)
        + matches[0].group(4)
    )
    updated_text = _PARAMETER_LINE.sub(lambda _: replacement, original_text, count=1)
    if dry_run:
        return expressions, None

    backup_root = (backup_dir or (project_dir.parent / ".pbi-workbook-path-backups"))
    backup_root = backup_root.expanduser().resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_root / f"{project_dir.name}-expressions-{timestamp}.tmdl.bak"
    shutil.copy2(expressions, backup_path)

    fd, temp_name = tempfile.mkstemp(prefix=".expressions-", suffix=".tmp", dir=expressions.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(updated_text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, expressions)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return expressions, backup_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a synthetic Gold export and set the PBIP's local workbook path."
    )
    parser.add_argument("--project", required=True, type=Path, help="PBIP file or project directory")
    parser.add_argument("--workbook", required=True, type=Path, help="DataForgeGold.xlsx path")
    parser.add_argument("--backup-dir", type=Path, help="backup folder (default: sibling .pbi-workbook-path-backups)")
    parser.add_argument("--dry-run", action="store_true", help="validate and report without writing")
    args = parser.parse_args()
    try:
        expressions, backup = configure_workbook_path(
            args.project,
            args.workbook,
            backup_dir=args.backup_dir,
            dry_run=args.dry_run,
        )
    except ConfigurationError as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(f"PASS: workbook validated; would configure {expressions}")
    elif backup is None:
        print(f"PASS: workbook validated; {expressions} already points to this workbook")
    else:
        print(f"PASS: workbook validated and configured in {expressions}")
        print(f"Backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
