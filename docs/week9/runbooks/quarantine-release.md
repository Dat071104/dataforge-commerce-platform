# Local quarantine release runbook

Status: local W9 harness procedure. It is not a live BigQuery release procedure.

## Symptom

A G1 P1 check returns `FAIL`. The batch is stored under `quarantine/<run_id>/`, with a manifest listing the failing check IDs and the published snapshot hash before and after the failed attempt.

## Triage

1. Open `quarantine/<run_id>/manifest.json` and confirm `status` is `QUARANTINED`.
2. Confirm `gold_sha256_before` equals `gold_sha256_after`.
3. Review `failed_check_ids` and compare the local candidate with the captured clean fixture. Do not edit the published snapshot to make the check pass.
4. Correct the quarantined candidate only after identifying the source or contract error. Preserve the original reason in the manifest.

## Deliberate release

After correction, run the local gate again and provide a reason for the release:

```powershell
python scripts/week9_fault_inject.py `
  --fault F01 `
  --dataset w9_drill `
  --root tests/week9/evidence/w9_drill `
  --report tests/week9/evidence/quarantine_demo_report.md
```

For the F01 captured-fixture demonstration, restore the affected province key from the unchanged captured fixture after reviewing the manifest:

```powershell
$runId = '<run_id printed by the injector>'
$asOfDate = '<as_of_date printed by the injector>'
@'
from pathlib import Path
import sys
import pandas as pd

root = Path('tests/week9/evidence/w9_drill')
candidate = root / 'quarantine' / sys.argv[1] / 'candidate.parquet'
repaired = pd.read_parquet(candidate)
clean = pd.read_parquet('tests/week9/faults/weather_7date_slice.parquet')
repaired.loc[0, 'province_id'] = clean.loc[0, 'province_id']
repaired.to_parquet(candidate, index=False)
'@ | python - $runId

```

Then rerun the local gate:

```powershell
python -m dataforge.dq.wap release `
  --root tests/week9/evidence/w9_drill `
  --run-id $runId `
  --date $asOfDate `
  --reason "<reviewed correction and evidence>"
```

The first command creates a persistent local last-good snapshot and one quarantined F01 candidate; use the reported `run_id` and `as_of_date` for the repair and release commands. The `--date` value must be on or after every observation date in the local snapshot. The release command validates the quarantined Parquet again with `DQ_ENFORCE=block`. A failing gate leaves the batch quarantined and the published hash unchanged. A passing gate updates the local published snapshot and records the new hash and release reason. If the repaired data is byte-identical to the last-good snapshot, the before and after hashes remain equal.

## Escalation and rollback

Escalate a persistent failure to the data owner and integrator with the manifest and check ID. Do not release while the contract or upstream cause is unresolved. For this local harness, rollback means restoring the saved `published/weather_landing.parquet` whose SHA-256 matches the last-good manifest. A live `w9_drill` or production release path requires separate integrator implementation and review; this runbook does not authorize cloud writes.
