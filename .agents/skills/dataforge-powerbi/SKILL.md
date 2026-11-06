---
name: dataforge-powerbi
description: Build or assess DataForge Power BI Desktop semantic model, DAX, relationships, pages and demo RLS without inventing a finished PBIX.
---

# Power BI workflow

1. Read `dashboards/POWER_BI_GUIDE.md`, `dashboards/P5/RELATIONSHIPS.csv`, semantic-model TMDL measures under `dashboards/P5/DataForge/DataForge.SemanticModel/definition/tables/`, and the relevant SQL view definitions.
2. Establish Import connection using user-supplied local credentials in Desktop only. No hardcoded passwords in M or repo.
3. Explicit 1-to-many single-direction relationships; mark dim_date calendar; separate order/payment/refund event-time semantics.
4. Verify DAX with known SQL controls and check report grain/cardinality. Never calculate sales from a raw multi-fact join.
5. Check RLS via View-as-role; inventory stock is global, not regional, so do not represent it as region-protected.
6. Produce real PBIP/PBIX only using supported Desktop interfaces and after testing. If unavailable, deliver draft M/DAX model pack and manual instructions labeled NOT VERIFIED.
