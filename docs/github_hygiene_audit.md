# GitHub repository hygiene audit

**Snapshot:** 13 November 2026, Asia/Bangkok. This is a read-only observation, not a ruleset or metadata change. GitHub configuration can change after this date; recheck before release.

Repository: [Dat071104/dataforge-commerce-platform](https://github.com/Dat071104/dataforge-commerce-platform)

## Observed settings

| Area | Snapshot | Evidence / meaning |
|---|---|---|
| Visibility and default branch | Public; default branch is <code>main</code>. | Visible on the [repository page](https://github.com/Dat071104/dataforge-commerce-platform). |
| About description | “Data Engineering platform for Vietnamese e-commerce analytics: Python, Parquet, PostgreSQL, Kimball modeling, SQL, Power BI, and automated data quality.” | Public repository metadata observed during this audit. |
| Topics and homepage | No topic badges or homepage URL were visible in the About section at the audit snapshot. | The existing description is accurate; no metadata changes were made. |
| Branch protection | No rulesets and no classic branch protection were visible in authenticated settings. | <code>main</code> is not currently protected by a visible repository-level rule. This may allow direct pushes or merges without a required review/check policy. |
| Pull requests | 0 open and 7 closed at the audit snapshot. | Existing release docs identify the previous phase PRs; P7.5 was still local/in progress at this snapshot. No P7.5 PR or merge is claimed here. |
| Merge options | Merge, squash, and rebase enabled; auto-merge disabled. | No setting changed. |
| Head-branch cleanup | Automatic head-branch deletion disabled. | Accepted feature branches remain available; no branch was deleted. |
| Tags and releases | No local or remote Git tags and no published GitHub releases were present at the snapshot. | <code>v1.0-local</code> is a documentation label, not a Git tag. No tag or release was created for P7.5. |
| PR template | No repository PR template existed before this documentation change. | This branch adds one at [.github/pull_request_template.md](../.github/pull_request_template.md); it takes effect only if merged. |
| Issue templates and policy changes | No issue template was present under <code>.github/</code>; no issue or ruleset changes were made. | Deferred work is drafted in [deferred issue scopes](roadmap/deferred_issue_drafts.md); no GitHub issues were created. |

The remote branches associated with accepted phases were retained. This audit did not delete branches, rewrite history, create tags, or modify metadata, merge options, branch rules, or collaborator permissions.

## About metadata proposal (not applied)

The current repository description already names the real stack and project purpose. A more portfolio-focused alternative would be:

> Evidence-first data engineering portfolio for synthetic commerce analytics, bounded GCP batch pipelines, local Spark, dbt, and Airflow.

Potential topics grounded in tracked code include <code>data-engineering</code>, <code>python</code>, <code>postgresql</code>, <code>dbt</code>, <code>apache-airflow</code>, <code>bigquery</code>, <code>pyspark</code>, <code>terraform</code>, and <code>power-bi</code>. No description, topic, homepage, or social-preview setting was changed.

## Pull-request history and scope lesson

Seven PRs were closed at this snapshot and their corresponding accepted records are retained in the repository. The release reports document CI repairs before earlier merges; the base CI and Week 7 CI also repeat broad regression work. P7.5 keeps Airflow correctness, Week 1/CI, and portfolio documentation in separate commits on one feature branch, and leaves CI structure and historical commits intact. Future work should keep changes centered on one acceptance slice and avoid expanding a docs or correctness PR into optional cloud deployment.

## Recommended main-branch rule

Prepare a ruleset targeting only <code>main</code>:

1. Require changes to enter through a pull request.
2. Require the stable CI checks observed on the eventual PR head; keep check names and branch-protection configuration aligned with the actual workflow output.
3. Block force-pushes and branch deletion.
4. Set human-review requirements only after confirming collaborator availability and a documented recovery/bypass path. Do not lock out the sole maintainer.
5. Review admin bypass and emergency recovery settings before enabling the rule.

This is a recommendation only. It is not applied because it can affect merge/recovery access and is outside the safe portfolio-document change.

## Follow-up release audit

Before merging P7.5, record the exact branch/head SHA, PR URL, all hosted check names and run IDs, review state, and branch-rule state. A green local test suite is not evidence that hosted checks passed. Do not describe an unmerged feature branch as released.
