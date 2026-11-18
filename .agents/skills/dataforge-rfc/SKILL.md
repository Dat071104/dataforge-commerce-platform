---
name: dataforge-rfc
description: Write, self-review and revise the DataForge Week 9 design doc (RFC-001) and ADRs in the author's voice, with alternatives, failure modes, SLOs, privacy, cost and an explicit decision log.
---

# RFC and ADR writing (Week 9 checkpoint)

1. Body of at most 2 pages (about 900-1,100 words). Everything else goes in appendices. Vietnamese prose, English technical terms, first person ("tôi"), no marketing words.
2. Sections: Context & problem (baseline numbers and the Oct30 false-positive incident), Goals / Non-goals, SLOs & error budget, Proposed design, Data contracts & change policy, Failure modes & detection map, Privacy & governance, Alternatives considered (each with the reason it was rejected), Cost & operations, Rollout & rollback (shadow mode, then enforce), Risks & open questions.
3. Every claim states its evidence level (unit / CI / live GCP / observed N days / mentor-approved) and links to the artifact. No artifact, no claim.
4. Alternatives are real options with trade-offs, not straw men. Open questions are questions the mentor can actually decide.
5. Review: one independent read-only reviewer in a mentor persona writes comments. Reply to every comment in the Decision log (accepted, or rejected with a reason). Never silently edit a comment away.
6. Status flow: Draft, In review, Accepted / Accepted with changes. Only the mentor moves it past In review. Until then the coverage row stays `MENTOR_CONFIRMATION_PENDING`.
7. ADRs: write the decision criteria **before** measuring. Record the measured numbers, the decision, consequences, and what would make you revisit it.
