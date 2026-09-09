# Open Formal Workflows

An advisory review workbench for [Formal Conjectures](https://github.com/google-deepmind/formal-conjectures).

- [Public overview](https://williamjblair.github.io/open-formal-workflows/)
- [Review queue and contribution evidence](https://williamjblair.github.io/open-formal-workflows/workbench/)

## Responsibilities

| Component | Owns |
| --- | --- |
| Formal Conjectures | Statements, pull requests, CI and maintainer decisions |
| FC contribution toolkit | Exact review inputs, reports, verification records and evidence validation |
| queueboard | Review classification and time actually waiting for review |
| This board | Queue presentation, shared-record consumption and links to FC |

The board does not assemble another review or infer a verification verdict from logs.
Evidence remains advisory. A passing check does not confer maintainer acceptance.

## Shared records

`shared_records.py` uses the commit-pinned FC toolkit reader. It validates archive manifests,
artifact hashes and input bindings before publishing `toolkit-evidence.json` to the renderer.
Unavailable, invalid, empty and unconfigured evidence remain distinct. The board retains its
queue even when evidence cannot be read.

The same build writes `work.json` with repository, observation time, exact PR head/base,
changed module paths and upstream links. The FC site can publish this snapshot for CLI `show`
and problem pages. A file match means related work; it is not proof of equivalent statements.
Queue rankings, waiting times and author/draft transitions still come from queueboard.

Evidence joins use exact repository/PR identities and compare the observed head/base.
Changed inputs make old reports historical without rewriting their outcome. The UI identifies
producers and links immutable bundles; hash validation is not producer authentication.

The configured fork evidence branch and toolkit commit are explicit in
`.github/workflows/board.yml`. This migration is delivered through its PR under
[FC #4394](https://github.com/google-deepmind/formal-conjectures/issues/4394), separately from
upstream adoption or enabling an FC website feed.

## Historical evidence

The [#4884 pilot](https://github.com/williamjblair/open-formal-workflows/tree/3300a105864c34ed97ad30a182496b3d570e0039/pilot)
records a Comparator invocation error, with parsing not attempted and axiom policy not
evaluated. Its hashes, original schema identifiers and URLs are preserved. That result is
not a mathematical rejection. The old `review_report.py`, `pilot.py`, and `fc_pr_audit.py`
remain historical readers and regression tools; the scheduled live build no longer invokes them.

Older numerical queue counts and legacy `fc-review-board` descriptions are historical in Git.
The published `fc-review-board.pr-audit-projection.v1` identifier is unchanged.

## Run locally

Use Python 3.12+, Node.js, authenticated `gh`, `jq`, and `uv`. Install the exact toolkit
revision recorded in the workflow, then:

```sh
./sync.sh
FC_EVIDENCE_REPOSITORY=williamjblair/formal-conjectures \
FC_EVIDENCE_BRANCH=codex/review-evidence-4899-20260909 python3 shared_records.py
python3 generate.py
python3 -m http.server
```

The workbench is at `/workbench/`. Generated snapshots are gitignored. No server or model
runtime is required to generate the page. Source documents, private workspaces and complete
agent transcripts are not uploaded by this consumer.

Run consumer and UI checks with:

```sh
python3 -m unittest test_shared_records test_ui_contract test_landing_contract
```

Historical-reader tests additionally require `FC_PR_AUDIT_SOURCE` pointing at the exact
`50fb575fadfc710f2da66cba1d3909429f9ba25e` audit checkout. They are not live dependencies.

Queue data and waiting-time logic come from
[queueboard-core](https://github.com/leanprover-community/queueboard-core), by Johan Commelin,
Michael Rothgang and Bryan Gin-ge Chen. This board remains an independent contributor project.
