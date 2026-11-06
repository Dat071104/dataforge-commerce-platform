# DataForge working agreement (main agent and all subagents)

Goal: complete Mini-projects 1+2 in a single local-first, technically defensible, Vietnamese Order-to-Cash analytics reference. Synthetic-first baseline; no invented business evidence.

**Read only when relevant:** `docs/architecture.md` for pipeline/schema work; `docs/metric_contract.md` for business metrics; `dashboards/POWER_BI_GUIDE.md` for Power BI; `docs/releases/v1.0-local.md` for latest released verification status.

- Never claim a test or deployment succeeded without recorded exit status/output. Update `docs/releases/v1.0-local.md` with release verification evidence.
- No mass refactor unless tests show need. Favor targeted, backwards-compatible patches with tests.
- Fact grain is immutable: one item != one payment != one return != one shipment. Aggregate each independently before reconciling by order.
- SCD2 as-of join uses `[valid_from,valid_to)` and excludes overlapping intervals.
- Business metric names state definitions; no fabricated recognized revenue, ROI, throughput, optimization %, or causality.
- Keep credentials in `.env`; no cloud access, push/commit, Power BI publish or external data download without appropriate user authorization.
- Python >=3.11,<3.14, Docker Postgres 16, pytest, Ruff; local-first. CLI must work without AI.
- Skills under `.agents/skills/` are opt-in focused procedures; main agent and workers load only matching skills.

## Delegation protocol

- For substantial independent work, use up to three workers with disjoint file ownership and explicit reports.
- If a phase invokes workers, wait for all worker reports before one independent controller review. The controller does not write code; it returns one evidence-based GO/REVISE/BLOCK verdict.
- Do not use subagents for trivial sequential work. Record release test commands and outcomes in `docs/releases/v1.0-local.md`.
