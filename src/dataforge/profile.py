"""External real-dataset discovery, without inventing schema mappings."""
from __future__ import annotations

import csv
import json
from pathlib import Path


def profile(directory: Path, output: Path) -> dict:
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    report: dict[str, dict] = {}
    for path in sorted(directory.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            columns = reader.fieldnames or []
            samples = [r for _, r in zip(range(5), reader)]
        report[path.name] = {
            "columns": columns,
            "sample_rows": samples,
            "note": "Only header and first five rows profiled; not a full data-quality audit",
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
