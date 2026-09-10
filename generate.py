#!/usr/bin/env python3
"""Render a review dashboard for formal-conjectures open PRs.

In the spirit of mathlib's queueboard: it turns the open PRs into one page so
maintainers can see what is ready to review, what is waiting on its author, and
what has waited longest. It also joins each Erdos-problem PR to the public Erdos
fidelity audit (https://erdos.constellate.science) and shows, per problem,
whether the linked proof was found unconditional, conditional, or signed by a
named reviewer. The audit surfaces a fact; the merge decision stays the
maintainer's.

generate.py fetches the open PRs (paginating gh api graphql) and the audit
feed, bakes them into one self-contained HTML file as JSON, and ships a small
vanilla-JS app that renders three views (queue / all / fidelity) with search,
faceted filters, sortable columns, and URL-bookmarkable state. No server, no
external fetch at view time.

    curl -sfL https://erdos.constellate.science/verdicts.json > verdicts.json
    python3 generate.py            # writes index.html
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
REPO = "google-deepmind/formal-conjectures"
BASE = "main"
STATEMENT_DIRS = ("ErdosProblems/", "Paper/", "Arxiv/", "Books/", "Wikipedia/",
                  "OEIS/", "OptimizationConstants/", "GreensOpenProblems/")

# The audit feed. Configurable so the board stays a neutral tool: point it at
# any compatible verdicts.json, or drop the column by pointing it at an empty
# feed.
COLLECTION_LABELS = {
    "erdos-problems": "Erdős", "oeis": "OEIS", "wikipedia": "Wikipedia",
    "arxiv": "arXiv", "paper": "papers", "Books": "books",
    "green-problems": "Green", "kourovka": "Kourovka",
    "written-on-the-wall": "WOWII", "open-quantum-problems": "quantum",
    "millenium-problems": "millennium", "HilbertProblems": "Hilbert",
    "mathoverflow": "MathOverflow",
}

VERDICTS_URL = os.environ.get("VERDICTS_URL", "")
# Where a per-problem finding lives, for the audit chips. Derived from the feed
# so nothing is hardcoded to one provider.
AUDIT_SITE = VERDICTS_URL.rsplit("/", 1)[0] if VERDICTS_URL else ""
FINDING_URL = (AUDIT_SITE + "/finding.html?n={n}") if AUDIT_SITE else "{n}"
ERDOS_URL = "https://www.erdosproblems.com/{n}"
ERDOS_FILE_RE = re.compile(r"ErdosProblems/(\d+)\.lean")

# Provenance pointers, present only when an audit feed is configured.
FRONTIER_URL = AUDIT_SITE
FC_REPO_URL = f"https://github.com/{REPO}"
FC_SITE_URL = "https://google-deepmind.github.io/formal-conjectures"
BOARD_REPO_URL = "https://github.com/williamjblair/open-formal-workflows"
LANDING_SITE_URL = "https://williamjblair.github.io/open-formal-workflows/"
BOARD_SITE_URL = f"{LANDING_SITE_URL}workbench/"
METHOD_URL = f"{BOARD_SITE_URL}#view=method"

# --- data -----------------------------------------------------------------
# PR state comes from queueboard, the same tool mathlib's review dashboard is
# built on. Its pipeline writes api/snapshot.json: a versioned
# {meta, lists, prs} document with each PR's classified status, CI state,
# labels, diff size and the cumulative time it has actually spent on the review
# queue. Consuming that means the fragile parts (paginating the GitHub API,
# parsing check rollups, deciding what "awaiting review" means) are maintained
# upstream rather than here.
#
# Three things queueboard does not carry are fetched separately: createdAt,
# whether the PR has a merge conflict, and when its checks last ran. That last
# one matters because a passing tick says nothing about the current main: 111
# of the open PRs import a module deleted in July and still show green, because
# their checks ran before the deletion. mergeStateStatus is computed on demand
# by GitHub, so this stays on small pages: 50 returns truncated responses
# under load and 100 502s outright.

SNAPSHOT = HERE / "snapshot.json"
BASICS = HERE / "pr_basics.json"
PR_AUDITS = HERE / "pr_audits.json"


def _unwrap(v):
    """queueboard tags some values as {__type__, __value__}; take the value."""
    return v.get("__value__") if isinstance(v, dict) and "__value__" in v else v


BUCKET = {"AwaitingReview": "review", "AwaitingAuthor": "author", "NotReady": "draft"}
CI = {"pass": "green", "fail": "failing"}


def load_snapshot() -> dict:
    if not SNAPSHOT.exists():
        raise SystemExit(f"{SNAPSHOT.name} not found. Run ./sync.sh first.")
    snap = json.loads(SNAPSHOT.read_text())
    if not snap.get("prs"):
        raise SystemExit("snapshot contains no PRs - refusing to write an empty board")
    return snap


def load_basics() -> dict[int, dict]:
    """`createdAt` and merge-conflict state, which the snapshot does not carry.

    sync.sh lifts these out of the per-PR data queueboard already downloaded. It
    used to be a second pass over the GitHub API here, which cost more than
    everything else in this script put together."""
    if not BASICS.exists():
        return {}
    return {int(k): v for k, v in json.loads(BASICS.read_text()).items()}


ISSUES = HERE / "issues.json"
BASE_PATHS = HERE / "base_paths.txt"


def main_paths() -> set[str]:
    """Every path on the base branch, written by sync.sh. Absent is fine: the supersession
    prompt just does not appear."""
    if not BASE_PATHS.exists():
        return set()
    return set(BASE_PATHS.read_text().split())
def load_issues(claimed: dict[int, list[int]] | None = None,
                base: set[str] | None = None) -> list[dict]:
    """Open issues, for the picking-something-up view. Written by sync.sh; absent is fine,
    the view just does not appear."""
    if not ISSUES.exists() or not ISSUES.read_text().strip():
        return []
    out = []
    for it in json.loads(ISSUES.read_text()):
        labels = [l["name"] for l in it.get("labels") or []]
        out.append({
            "n": it["number"],
            "title": it["title"],
            "labels": labels,
            # The template has the author tick either "I plan on working on this" or "up for
            # grabs". Going by labels alone lists conjectures their author has claimed.
            "ready": ("new conjecture" in labels and "needs-prerequisites" not in labels
                      and it.get("upForGrabs", True)),
            "ams": next((l.split(":")[0].replace("ams-", "AMS ").strip()
                         for l in labels if l.startswith("ams-")), ""),
            "age": days_since(it["createdAt"], datetime.now(timezone.utc)),
            "prs": sorted((claimed or {}).get(it["number"], [])),
            "have": already_stated(it["title"], base or set()),
        })
    return out


ERDOS_TITLE_RE = re.compile(r"Erd[őo]s Problem (\d+)")


def already_stated(title: str, base: set[str]) -> str:
    """The file already on the base branch that this issue asks for, if any.

    Only exact for issues titled `Erdős Problem N`, which is 279 of the 444 unclaimed ones.
    An issue stays open after the conjecture lands, so without this the list sends people to
    write something the repository already has.
    """
    m = ERDOS_TITLE_RE.search(title)
    if not m:
        return ""
    path = f"FormalConjectures/ErdosProblems/{m.group(1)}.lean"
    return path if path in base else ""


CLOSES_RE = re.compile(r"\b(?:closes|fixes|resolves|close|fix|resolve)\s+#(\d+)", re.I)


def claims(snapshot: dict) -> dict[int, list[int]]:
    """Issue number -> the open PRs saying they close it.

    The site knows what problems exist and GitHub knows what is in flight; nobody joins the
    two, so a conjecture with an open PR against it looks exactly as unclaimed as one without.
    That is how the same problem gets formalised twice.
    """
    out: dict[int, list[int]] = {}
    for num, pr in (snapshot.get("prs") or {}).items():
        for issue in set(CLOSES_RE.findall(pr.get("description") or "")):
            out.setdefault(int(issue), []).append(int(num))
    return out


def load_verdicts() -> dict[int, dict]:
    """Index the audit feed by problem number. Prefer a local verdicts.json
    (the Action curls it, tests drop it in); otherwise fetch the live feed."""
    cache = HERE / "verdicts.json"
    url = VERDICTS_URL
    if cache.exists():
        data = json.loads(cache.read_text())
    elif url:
        with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310
            data = json.loads(r.read().decode())
    else:
        return {}
    rows = data.get("rows", []) if isinstance(data, dict) else data
    return {r["problem"]: r for r in rows if "problem" in r}


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key in audit feed: {key}")
        out[key] = value
    return out


def load_pr_audits() -> dict[int, dict]:
    """Load the exact per-PR advisory projection when it is present."""
    if not PR_AUDITS.exists():
        return {}
    from fc_pr_audit import validate_projection
    data = json.loads(PR_AUDITS.read_text(), object_pairs_hook=_unique_pairs)
    validate_projection(data)
    return {row["pull_request"]["number"]: row for row in data["rows"]}


def load_pilot() -> dict | None:
    """Read the shared toolkit projection; historical pilot files are not live inputs."""
    path=HERE/'toolkit-evidence.json'
    if not path.is_file():return None
    from conjectures import report as rr
    value=rr.read_json(path)
    if value.get('schema_version')!='fc.contribution-context.v1' or value.get('authority_effect')!='none':
        raise ValueError('Invalid shared contribution context')
    if any(run.get('validation')!='validated_bundle' for run in value.get('runs',[])):
        raise ValueError('Unvalidated contribution evidence')
    return value


# --- classification -------------------------------------------------------
# Buckets, CI state and idle time are queueboard's, not ours. What stays here
# is the FC-specific reading: whether a PR touches a statement file, and how
# long it has been waiting.

def ci_state(pr: dict) -> str:
    return CI.get(_unwrap(pr.get("ci_status")), "none")


def maybe_superseded(basic: dict, main_paths: set[str]) -> bool:
    """Every file this PR adds is already on the base branch, so the work may have landed
    another way.

    A prompt, not a verdict. "Adds" here means "no deletions", which is as close as the data
    gets; a PR that only appends to an existing file looks the same. The file cap keeps out
    branches with an ancient base, which report hundreds of files and would otherwise all
    match."""
    added = basic.get("addedFiles") or []
    return 0 < len(added) <= 5 and all(f in main_paths for f in added)


def is_statement(pr: dict) -> bool:
    return any(p.startswith("FormalConjectures/") and any(d in p for d in STATEMENT_DIRS)
               for p in pr.get("modified_files") or [])


def approvals(pr: dict) -> int:
    return len(pr.get("approvals") or [])


# Changes on `main` that break branches predating them. "CI is N days old" is a proxy for
# this; naming the change is sharper, since it separates a branch that is merely old from one
# whose tick was earned against a `main` that no longer exists. Add an entry when you land
# something that breaks existing branches.
BREAKING_CHANGES = [
    ("2026-07-17T00:00:00Z",
     "FormalConjectures.Util.ProblemImports was deleted (#4433); "
     "these branches need `import FormalConjecturesUtil` and a rebase"),
    ("2026-08-02T16:22:00Z",
     "the openClassical linter was switched on (#4671); a branch adding "
     "`open Classical` now fails under --wfail"),
]


def stale_reason(ran: str | None) -> str | None:
    """The most recent breaking change on `main` that this PR's checks predate."""
    if not ran:
        return None
    for when, what in sorted(BREAKING_CHANGES, reverse=True):
        if ran < when:
            return what
    return None


def ci_ran_at(basic: dict) -> str | None:
    """When this PR's checks last completed."""
    try:
        return (basic["commits"]["nodes"][0]["commit"]["statusCheckRollup"]
                ["contexts"]["nodes"][0]["completedAt"])
    except (KeyError, IndexError, TypeError):
        return None


def has_conflict(pr: dict, basic: dict) -> bool:
    return (basic.get("mergeStateStatus") or "").upper() == "DIRTY"


def days_since(iso: str, now: datetime) -> int:
    return (now - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days


def queue_days(pr: dict) -> int | None:
    """Time actually spent on the review queue, excluding spells where the ball
    was in the author's court. None when queueboard could not reconstruct it."""
    t = pr.get("total_queue_time") or {}
    if t.get("status") != "valid" or not t.get("value_td"):
        return None
    return round(t["value_td"] / 86400)


def idle_days(pr: dict) -> int | None:
    """Days since the PR's status last changed."""
    lsc = pr.get("last_status_change") or {}
    if lsc.get("status") != "valid":
        return None
    d = lsc.get("delta") or {}
    return round(d.get("months", 0) * 30 + d.get("days", 0) + d.get("hours", 0) / 24)


def classify(pr: dict, approved: set[int], number: int) -> str:
    if number in approved:
        return "approved"
    return BUCKET.get(_unwrap(pr.get("pr_status")), "draft")



# --- audit join -----------------------------------------------------------

def problem_numbers(pr: dict) -> list[int]:
    nums = set()
    for path in pr.get("modified_files") or []:
        m = ERDOS_FILE_RE.search(path)
        if m:
            nums.add(int(m.group(1)))
    return sorted(nums)


def _assumptions(row: dict) -> str:
    """Readable form of the Prop hypotheses a conditional proof rests on:
    'hconv : Erdos94.ConvexPosition P' -> 'ConvexPosition P'."""
    labels = []
    for na in row.get("named_assumptions") or []:
        t = na.split(":", 1)[-1].strip()
        labels.append(re.sub(r"\bErdos\d+\.", "", t))
    return ", ".join(labels)


def audit_class(row: dict | None) -> tuple[str, str]:
    """Map an audit row to a (badge-class, tooltip-note). The base colour comes
    from the machine verdict; a signed human verdict overrides it."""
    if row is None:
        return "ab--none", "not in the audit feed"
    signed = row.get("signed_fidelity_verdict")
    mv = row.get("machine_verdict")
    by = row.get("signed_by") or ""
    if signed == "faithful":
        return "ab--signed", f"signed faithful by {by}"
    if signed == "unfaithful":
        return "ab--discrepancy", f"signed unfaithful by {by}"
    if signed == "variant":
        return "ab--variant", f"signed variant by {by}"
    if mv == "unconditional":
        return "ab--unconditional", "machine-checked, unconditional"
    if mv == "conditional":
        asm = _assumptions(row)
        return "ab--conditional", "conditional" + (f": assumes {asm}" if asm else "")
    return "ab--unaudited", f"not yet audited ({row.get('bucket', 'open')})"


# Severity order (highest first): a PR's headline audit status is the most
# notable thing found among its problems. Maps class -> facet status key.
SEVERITY = ["ab--discrepancy", "ab--conditional", "ab--variant",
            "ab--signed", "ab--unconditional"]
STATUS_KEY = {"ab--signed": "signed", "ab--unconditional": "unconditional",
              "ab--conditional": "conditional", "ab--variant": "conditional",
              "ab--discrepancy": "flagged", "ab--unaudited": "unaudited",
              "ab--none": "unaudited"}


def pr_top_status(audit: list[dict]) -> str | None:
    classes = {a["cls"] for a in audit}
    for s in SEVERITY:
        if s in classes:
            return s
    return None


def build_record(number: int, pr: dict, basic: dict, verdicts: dict[int, dict],
                 pr_audits: dict[int, dict],
                 approved: set[int], now: datetime, on_main: set[str]) -> dict:
    audit = []
    for n in problem_numbers(pr):
        row = verdicts.get(n)
        cls, note = audit_class(row)
        href = ERDOS_URL.format(n=n) if row is None else FINDING_URL.format(n=n)
        audit.append({"n": n, "cls": cls, "status": STATUS_KEY[cls],
                      "note": note, "href": href})
    ci = ci_state(pr)
    created = basic.get("createdAt")
    # Prefer time on the queue; fall back to age when queueboard could not
    # reconstruct the timeline (PRs synced with the reduced query).
    waiting = queue_days(pr)
    age = days_since(created, now) if created else (waiting or 0)
    idle = idle_days(pr)
    return {
        "n": number,
        "title": pr.get("title") or "",
        "author": pr.get("author") or "ghost",
        "kind": "statement" if is_statement(pr) else "infra",
        "coll": sorted({COLLECTION_LABELS[l["name"]] for l in (pr.get("labels") or [])
                        if l["name"] in COLLECTION_LABELS}),
        "bucket": classify(pr, approved, number),
        "ci": ci,
        "ciPending": (not pr.get("is_draft")) and ci == "none",
        "conflict": has_conflict(pr, basic),
        "age": age,
        "waiting": waiting,
        "idle": idle if idle is not None else age,
        "appr": approvals(pr),
        "who": sorted(pr.get("assignees") or []),
        "ciAge": (days_since(ran, now) if (ran := ci_ran_at(basic)) else None),
        "staleWhy": stale_reason(basic.get("headDate")) or "",
        "onMain": maybe_superseded(basic, on_main),
        "churn": (pr.get("additions") or 0) + (pr.get("deletions") or 0),
        "audit": audit,
        "auditTop": pr_top_status(audit),
        "auditStatuses": sorted({a["status"] for a in audit}),
        "prAudit": pr_audits.get(number),
    }


def main() -> None:
    snap = load_snapshot()
    basics = load_basics()
    verdicts = load_verdicts()
    pr_audits = {}  # Old audit projections remain historical; toolkit records own the live path.
    pilot_bundle = load_pilot()
    approved = set(snap.get("lists", {}).get("dashboards", {}).get("Approved") or [])
    now = datetime.now(timezone.utc)
    on_main = main_paths()
    issues = load_issues(claims(snap), on_main)
    records = [build_record(int(num), pr, basics.get(int(num), {}), verdicts, pr_audits,
                            approved, now,
                            on_main)
               for num, pr in snap["prs"].items()]
    for record in records:
        record['contributionEvidence']=[run for run in (pilot_bundle or {}).get('runs',[])
            if run.get('target',{}).get('pr')==record['n'] and
               run.get('target',{}).get('repository') in (REPO,'https://github.com/'+REPO)]
    records.sort(key=lambda r: -(r["waiting"] if r["waiting"] is not None else r["age"]))
    joined_pr_audits = [record for record in records if record["prAudit"] is not None]
    meta = {
        "generated": now.strftime("%Y-%m-%d %H:%M UTC"),
        "repo": REPO, "hasAudit": bool(verdicts),
        "hasPrAudit": bool(joined_pr_audits), "hasPrAuditFeed": bool(pr_audits),
        "hasIssues": bool(issues), "hasPilot": pilot_bundle is not None,
    }
    compact = {"ensure_ascii": False, "separators": (",", ":")}
    data = json.dumps(records, **compact).replace("</", "<\\/")
    doc = (TEMPLATE
           .replace("__DATA__", data)
           .replace("__PR_AUDITS__", json.dumps(list(pr_audits.values()), **compact)
                    .replace("</", "<\\/"))
           .replace("__PILOT__", json.dumps(pilot_bundle, **compact)
                    .replace("</", "<\\/"))
           .replace("__ISSUES__", json.dumps(issues, **compact).replace("</", "<\\/"))
           .replace("__META__", json.dumps(meta, **compact).replace("</", "<\\/"))
           .replace("__STAMP__", meta["generated"])
           .replace("__FC_REPO__", FC_REPO_URL)
           .replace("__FC_SITE__", FC_SITE_URL)
           .replace("__BOARD_REPO__", BOARD_REPO_URL)
           .replace("__BOARD_SITE__", BOARD_SITE_URL)
           .replace("__LANDING_SITE__", LANDING_SITE_URL)
           .replace("__METHOD__", METHOD_URL)
           .replace("__FRONTIER__", FRONTIER_URL)
           .replace("__PR_AUDIT_NOTE__", (
               '<p><strong>The PR audit column</strong> is a deterministic projection of '
               'the exact source-local FC audit records. Its labels are advisory evidence, '
               'not approval, merge readiness, mathematical truth, or Repository authority.</p>'
               if pr_audits else "")))
    if not verdicts:
        doc = re.sub(r"\s*<p><strong>The audit column</strong>.*?</p>", "", doc, flags=re.S)
        doc = re.sub(r"\s*<p>PR data via the GitHub API\..*?</p>",
                     "\n  <p>PR data via the GitHub API. PR state, timings and CI classification "
                     "via <a href=\"https://github.com/leanprover-community/queueboard-core\">"
                     "queueboard</a>, the tool mathlib's review dashboard is built on. "
                     "An independent tool, not affiliated with the formal-conjectures "
                     "maintainers.</p>", doc, flags=re.S)
    workbench = HERE / "workbench"
    workbench.mkdir(exist_ok=True)
    (workbench / "index.html").write_text(doc)
    review = [r for r in records if r["bucket"] == "review"]
    longest = max((r["waiting"] or r["age"] for r in review), default=0)
    print(f"wrote workbench/index.html - {len(records)} PRs, {len(review)} ready for "
          f"review ({sum(1 for r in review if r['kind'] == 'statement')} "
          f"statements), longest waiting {longest}d")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Open Formal Workflows | Formal Conjectures Review, Verification &amp; Preservation</title>
<meta name="application-name" content="Open Formal Workflows">
<meta name="description" content="Formal Conjectures review, verification, and preservation pilot. Advisory evidence only; Formal Conjectures retains authority.">
<link rel="canonical" href="__BOARD_SITE__">
<meta property="og:title" content="Open Formal Workflows | Formal Conjectures Review, Verification &amp; Preservation">
<meta property="og:description" content="A bounded advisory evidence pilot for Formal Conjectures review, verification, and preservation.">
<meta property="og:url" content="__BOARD_SITE__">
<link rel="icon" href="../assets/favicon.svg" type="image/svg+xml">
<style>
:root {
  /* Restrained evidence palette: cool paper, one blue link accent, and semantic
     colors reserved for typed outcomes and freshness. */
  --paper: oklch(97.2% 0.008 248); --panel: oklch(93.4% 0.011 250); --card: oklch(99.2% 0.004 248);
  --ink0: oklch(20% 0.030 262); --ink1: oklch(38% 0.026 258); --ink2: oklch(54% 0.018 252);
  --rule: color-mix(in oklab, var(--ink0) 12%, transparent);
  --rule2: color-mix(in oklab, var(--ink0) 22%, transparent); --hover: var(--ink0);
  --accent: oklch(40% 0.072 252);
  --ok: oklch(52% 0.075 145); --bad: oklch(52% 0.12 34); --run: oklch(66% 0.10 80);
  --stmt: oklch(40% 0.060 250); --infra: oklch(54% 0.018 252);
  --moss: oklch(43.5% 0.043 128); --brass: oklch(45.5% 0.082 83);
  --gold: oklch(72% 0.130 86); --gold-ink: oklch(46.8% 0.102 82);
  --gold-glow: color-mix(in oklab, var(--gold) 20%, transparent);
  --stone: oklch(55% 0.022 80); --cinnabar: oklch(49.5% 0.128 35);
}
@media (prefers-color-scheme: dark) {
  :root {
    /* The same evidence hierarchy in low ambient light. */
    --paper: oklch(17.4% 0.024 252); --panel: oklch(22% 0.026 254); --card: oklch(20.6% 0.024 253);
    --ink0: oklch(92% 0.012 258); --ink1: oklch(74% 0.016 256); --ink2: oklch(60% 0.016 256);
    --rule: color-mix(in oklab, var(--ink0) 16%, transparent);
    --rule2: color-mix(in oklab, var(--ink0) 28%, transparent); --hover: var(--ink0);
    --accent: oklch(74% 0.058 250);
    --ok: oklch(66% 0.085 145); --bad: oklch(64% 0.13 35); --run: oklch(76% 0.10 80);
    --stmt: oklch(74% 0.060 250); --infra: oklch(62% 0.016 256);
    --moss: oklch(60% 0.055 128); --brass: oklch(62% 0.095 83);
    --gold: oklch(77% 0.120 85); --gold-ink: oklch(80% 0.100 84);
    --gold-glow: color-mix(in oklab, var(--gold) 16%, transparent);
    --stone: oklch(64% 0.020 258); --cinnabar: oklch(64% 0.130 35);
  }
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin: 0; background: var(--paper); color: var(--ink0);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  -webkit-font-smoothing: antialiased; }
.wrap { max-width: 1120px; margin: 0 auto; padding: 30px 24px 64px; }
a { color: var(--accent); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
main:focus { outline: none; }

header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 20px;
  margin-bottom: 14px; }
h1 { display: flex; flex-direction: column; gap: 1px; margin: 0; }
h1 .product-name { font-size: 23px; font-weight: 660; letter-spacing: -.015em; }
h1 .h1-sub { color: var(--ink2); font-size: 13.5px; font-weight: 500; letter-spacing: .005em; }
.meta { margin-left: auto; font-size: 12.5px; color: var(--ink2); }
.meta a { color: var(--ink1); text-decoration: none; border-bottom: 1px solid var(--rule2); }
.meta a:hover { color: var(--accent); border-color: var(--accent); }
.sep { margin: 0 8px; color: var(--rule2); }
.boundary { display: flex; align-items: flex-start; gap: 12px; margin: 0 0 14px;
  padding: 10px 12px; border: 1px solid var(--rule2); border-radius: 10px;
  background: color-mix(in oklab, var(--accent) 5%, var(--card)); color: var(--ink1); }
.boundary strong { color: var(--ink0); font-size: 12px; letter-spacing: .035em;
  text-transform: uppercase; white-space: nowrap; }
.boundary span { max-width: 86ch; font-size: 12.5px; }
.boundary a { white-space: nowrap; }

/* Overview: a slim typographic row, not a filled card. */
.strip { display: flex; flex-wrap: wrap; align-items: baseline; gap: 9px 22px;
  padding: 2px 0 18px; margin: 4px 0 0; }
.grp { display: flex; flex-wrap: wrap; gap: 9px 20px; align-items: baseline; }
.grp--audit { position: relative; padding-left: 24px; }
.grp--audit::before { content: ""; position: absolute; left: 0; top: 3px; bottom: 3px;
  width: 1px; background: var(--rule2); }
.stat { display: flex; align-items: baseline; gap: 6px; }
.stat--go { border: 0; background: none; padding: 2px 7px; margin: -2px -7px; border-radius: 5px;
  font: inherit; cursor: pointer; }
.stat--go:hover { background: var(--rule); }
.stat--go.is-on { background: var(--rule); box-shadow: inset 0 0 0 1px var(--rule2); }
.stat--go:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.sv { font-size: 18px; font-weight: 660; font-variant-numeric: tabular-nums;
  letter-spacing: -.01em; color: var(--ink0); }
.sl { font-size: 12.5px; color: var(--ink2); }
.sv--gold { color: var(--gold-ink); } .sv--brass { color: var(--brass); } .sv--cinnabar { color: var(--cinnabar); }

/* One sticky control bar: search + views on top, filters below. */
.controls { position: sticky; top: 0; z-index: 5; background: var(--paper);
  padding: 11px 0; margin-bottom: 10px; border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule); }
.controls-row { display: flex; align-items: center; gap: 10px 14px; flex-wrap: wrap; }
.controls-row + .controls-row { margin-top: 11px; }
.spacer { margin-left: auto; }
.search { position: relative; display: flex; align-items: center; }
.search .s-icon { position: absolute; left: 10px; width: 14px; height: 14px;
  fill: var(--ink2); pointer-events: none; }
.search input { font: inherit; font-size: 13px; padding: 6px 11px 6px 30px; width: 230px; max-width: 62vw;
  background: var(--card); color: var(--ink0); border: 1px solid var(--rule2); border-radius: 8px; }
.search input::placeholder { color: var(--ink2); }
.filterbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.fdd { position: relative; }
.fbtn { display: inline-flex; align-items: center; gap: 5px; font: inherit; font-size: 13px;
  padding: 5px 11px; border-radius: 8px; border: 1px solid var(--rule2); background: var(--card);
  color: var(--ink1); cursor: pointer; transition: all .12s ease; }
.fbtn:hover { border-color: var(--ink2); color: var(--ink0); }
.fbtn.active { color: var(--accent); border-color: color-mix(in oklab, var(--accent) 42%, transparent);
  background: color-mix(in oklab, var(--accent) 10%, transparent); }
.fbtn-n { font-variant-numeric: tabular-nums; font-weight: 660; }
.fbtn svg { opacity: .55; transition: transform .12s ease; }
.fdd.open .fbtn svg { transform: rotate(180deg); }
.fmenu { position: absolute; top: calc(100% + 5px); left: 0; z-index: 20; min-width: 172px;
  background: var(--card); border: 1px solid var(--rule2); border-radius: 10px; padding: 5px;
  box-shadow: 0 8px 24px color-mix(in oklab, var(--ink0) 18%, transparent); }
.fopt { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px;
  font-size: 13px; color: var(--ink1); cursor: pointer; text-transform: capitalize; }
.fopt:hover { background: color-mix(in oklab, var(--hover) 6%, transparent); }
.fopt input { accent-color: var(--accent); margin: 0; cursor: pointer; }
.clear-btn { font: inherit; font-size: 12.5px; color: var(--ink2); background: none; border: 0;
  cursor: pointer; padding: 5px 4px; }
.clear-btn:hover { color: var(--accent); text-decoration: underline; }
.cdot { width: 8px; height: 8px; border-radius: 3px; display: inline-block; border: 1px solid transparent; }
.cdot--moss { background: color-mix(in oklab, var(--moss) 55%, transparent); }
.cdot--brass { background: color-mix(in oklab, var(--brass) 60%, transparent); }
.cdot--stone { background: color-mix(in oklab, var(--stone) 42%, transparent); }
.cdot--gold { background: var(--gold-glow); border-color: color-mix(in oklab, var(--gold) 55%, transparent); }
.cdot--cinnabar { background: color-mix(in oklab, var(--cinnabar) 45%, transparent); }
.tabs { display: flex; max-width: 100%; gap: 3px; overflow-x: auto; background: var(--panel);
  border: 1px solid var(--rule); border-radius: 9px; padding: 3px; }
.tab { font: inherit; font-size: 13px; padding: 4px 13px; border-radius: 7px; border: 0;
  background: none; color: var(--ink1); cursor: pointer; white-space: nowrap; transition: all .12s ease; }
.tab:hover { color: var(--ink0); }
.tab.active { background: var(--card); color: var(--ink0); font-weight: 640;
  box-shadow: 0 1px 2px color-mix(in oklab, var(--ink0) 12%, transparent); }
.count { font-size: 12.5px; color: var(--ink2); font-variant-numeric: tabular-nums; white-space: nowrap; }
.caret { vertical-align: middle; margin-left: 3px; }
.caret.up { transform: rotate(180deg); }

section { margin: 22px 0; }
.view-intro { display: flex; align-items: baseline; justify-content: space-between; gap: 18px;
  margin: 18px 0 6px; }
.view-intro h2 { margin: 0; font-size: 18px; letter-spacing: -.012em; }
.view-intro p { max-width: 68ch; margin: 0; color: var(--ink1); font-size: 13.5px; }
.sec-h { display: flex; align-items: baseline; gap: 8px; margin: 0 0 9px; }
.sec-h h2 { font-size: 14px; font-weight: 640; margin: 0; letter-spacing: -.005em; }
.sec-h .n { font-size: 12px; color: var(--ink2); font-weight: 500; font-variant-numeric: tabular-nums; }
.scroll { overflow-x: auto; border: 1px solid var(--rule); border-radius: 12px; }
table { width: 100%; border-collapse: collapse; background: var(--card); }
.pr-table { min-width: 930px; }
th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
  color: var(--ink2); font-weight: 640; padding: 9px 12px; background: var(--panel);
  border-bottom: 1px solid var(--rule); white-space: nowrap; }
th.sortable { user-select: none; }
th.sortable:hover { color: var(--ink1); }
th.active { color: var(--ink0); }
.sorter { display: inline-flex; align-items: center; gap: 2px; padding: 0; border: 0;
  background: none; color: inherit; font: inherit; letter-spacing: inherit; text-transform: inherit;
  cursor: pointer; }
.sorter:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
td { padding: 9px 12px; border-bottom: 1px solid var(--rule); font-size: 14px; }
tr:last-child td { border-bottom: 0; }
tbody tr { transition: background .12s ease; }
tbody tr:hover { background: color-mix(in oklab, var(--hover) 4%, transparent); }
.num a { color: var(--accent); text-decoration: none; font-variant-numeric: tabular-nums; font-weight: 640; }
.num a:hover { color: var(--gold-ink); text-decoration: underline; }
.ttl { max-width: 440px; }
.ttl-t { display: inline-block; max-width: 440px; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; vertical-align: bottom; color: var(--ink0); }
.who { color: var(--ink1); white-space: nowrap; }
.mono { font-variant-numeric: tabular-nums; color: var(--ink1); text-align: right; white-space: nowrap; }
.tag { font-size: 11px; padding: 2px 8px; border-radius: 999px; font-weight: 640; white-space: nowrap; }
.tag--statement { background: color-mix(in oklab, var(--stmt) 12%, transparent); color: var(--stmt); }
.tag--infra { background: color-mix(in oklab, var(--infra) 13%, transparent); color: var(--infra); }
.audit { max-width: 240px; }
.ab { display: inline-block; font-size: 11px; font-variant-numeric: tabular-nums; font-weight: 650;
  text-decoration: none; padding: 1px 6px; margin: 1px 3px 1px 0; border-radius: 5px;
  border: 1px solid transparent; }
.ab:hover { filter: brightness(1.04) saturate(1.1); }
.ab--unconditional { color: var(--moss); background: color-mix(in oklab, var(--moss) 13%, transparent);
  border-color: color-mix(in oklab, var(--moss) 38%, transparent); }
.ab--conditional { color: var(--brass); background: color-mix(in oklab, var(--brass) 14%, transparent);
  border-color: color-mix(in oklab, var(--brass) 40%, transparent); }
.ab--unaudited, .ab--none { color: var(--stone); background: none; border-color: var(--rule2); }
.ab--signed { color: var(--gold-ink); background: var(--gold-glow);
  border-color: color-mix(in oklab, var(--gold) 55%, transparent); }
.ab--variant { color: var(--brass); background: color-mix(in oklab, var(--brass) 14%, transparent);
  border-color: color-mix(in oklab, var(--gold) 55%, transparent); }
.ab--discrepancy { color: var(--cinnabar); background: color-mix(in oklab, var(--cinnabar) 12%, transparent);
  border-color: color-mix(in oklab, var(--cinnabar) 42%, transparent); }
.pa { white-space: nowrap; }
.pa--needs_revision { color: var(--cinnabar); background: color-mix(in oklab, var(--cinnabar) 12%, transparent);
  border-color: color-mix(in oklab, var(--cinnabar) 42%, transparent); }
.pa--inconclusive { color: var(--brass); background: color-mix(in oklab, var(--brass) 14%, transparent);
  border-color: color-mix(in oklab, var(--brass) 40%, transparent); }
.pa--unavailable { color: var(--stone); background: none; border-color: var(--rule2); }
.roll { display: flex; flex-wrap: wrap; align-items: center; gap: 3px; font-size: 12px; color: var(--ink2); }
.roll b { color: var(--ink0); font-variant-numeric: tabular-nums; margin-right: 3px; }
.rc { display: inline-block; font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums;
  padding: 0 5px; border-radius: 5px; border: 1px solid transparent; }
.ci { display: inline-block; width: 9px; height: 9px; border-radius: 999px; }
.ci--ok { background: var(--ok); } .ci--bad { background: var(--bad); }
.ci--run { background: var(--run); } .ci--na { background: var(--rule2); }
.appr { color: var(--moss); font-weight: 650; }
.appr-c { text-align: center; }
.prlink { font-variant-numeric: tabular-nums; text-decoration: none; color: var(--accent);
  font-weight: 600; font-size: 13px; margin-right: 2px; }
.prlink:hover { color: var(--gold-ink); }
.flag { display: inline-block; font-size: 10px; font-weight: 650; padding: 1px 6px; margin-left: 6px;
  border-radius: 5px; vertical-align: middle; text-transform: uppercase; letter-spacing: .03em; }
.flag--ci { background: color-mix(in oklab, var(--run) 18%, transparent);
  color: color-mix(in oklab, var(--run) 55%, var(--ink0)); }
.flag--conflict { background: color-mix(in oklab, var(--cinnabar) 15%, transparent); color: var(--cinnabar); }
.flag--rebase { background: color-mix(in oklab, var(--brass) 16%, transparent); color: var(--brass); }
.flag--ok { background: color-mix(in oklab, var(--ok) 15%, transparent); color: var(--ok); }
.flag--onmain { background: color-mix(in oklab, var(--stone) 16%, transparent); color: var(--stone); }
.empty { padding: 44px 12px; text-align: center; color: var(--ink2); font-size: 14px; }
.linkish { font: inherit; color: var(--accent); background: none; border: 0; cursor: pointer; text-decoration: underline; }
.skip { position: fixed; left: 12px; top: 8px; z-index: 10; transform: translateY(-160%);
  padding: 9px 12px; border-radius: 6px; background: var(--ink0); color: var(--card); }
.skip:focus { transform: none; }
.audit-records { border-top: 1px solid var(--rule); }
.audit-record { padding: 18px 0; border-bottom: 1px solid var(--rule); }
.audit-record-h { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; }
.audit-record-h a { color: var(--accent); text-decoration: none; }
.audit-record-h a:hover { color: var(--gold-ink); text-decoration: underline; }
.audit-record ul { margin: 12px 0; padding-left: 22px; color: var(--ink1); line-height: 1.65; }
.audit-record p { margin: 0; overflow-wrap: anywhere; text-align: left; white-space: normal; }

/* Bounded pilot: one case, with source identity and uncertainty kept visible. */
.pilot-head { display: block; margin: 0; padding: 26px 0 22px; border-bottom: 1px solid var(--rule2); }
.eyebrow { margin: 0 0 7px; color: var(--ink2); font-size: 11px; font-weight: 700;
  letter-spacing: .075em; text-transform: uppercase; }
.pilot-head h2 { margin: 0; max-width: 32ch; font-size: 27px; line-height: 1.2;
  letter-spacing: -.022em; font-weight: 670; }
.pilot-summary { max-width: 70ch; margin: 12px 0 0; color: var(--ink1); }
.pilot-links, .state-line { display: flex; flex-wrap: wrap; gap: 7px 14px; margin-top: 15px; }
.pilot-links a { font-size: 12.5px; text-decoration: none; border-bottom: 1px solid var(--rule2); }
.pilot-links a:hover { border-color: var(--accent); }
.state { display: inline-flex; align-items: center; gap: 6px; padding: 3px 8px;
  border: 1px solid var(--rule2); border-radius: 999px; color: var(--ink1);
  background: var(--card); font-size: 11.5px; font-weight: 640; }
.state::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--stone); }
.state--current::before { background: var(--ok); }
.state--stale::before { background: var(--bad); }
.state--open::before { background: var(--run); }
.pilot-section { margin: 30px 0 0; }
.pilot-section-h { display: flex; align-items: baseline; justify-content: space-between;
  gap: 16px; padding-bottom: 8px; border-bottom: 1px solid var(--rule2); }
.pilot-section-h h3 { margin: 0; font-size: 15px; letter-spacing: -.005em; }
.pilot-section-h p { margin: 0; color: var(--ink2); font-size: 12px; }
.evidence-row { display: grid; grid-template-columns: minmax(150px, .8fr) minmax(260px, 2fr) minmax(120px, .7fr);
  gap: 20px; align-items: start; padding: 14px 0; border-bottom: 1px solid var(--rule); }
.evidence-name { font-weight: 640; }
.evidence-source { color: var(--ink1); }
.evidence-source small { display: block; margin-top: 3px; color: var(--ink2); }
.outcome { display: inline-flex; align-items: center; justify-self: start; gap: 7px;
  color: var(--ink1); font-size: 12px; font-weight: 680; }
.outcome::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--stone); }
.outcome--error { color: var(--cinnabar); }
.outcome--pending { color: var(--brass); }
.outcome--pass::before { background: var(--ok); }
.outcome--error::before { background: var(--bad); }
.outcome--pending::before { background: var(--run); }
.pilot-split { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(260px, .85fr);
  gap: 38px; margin-top: 18px; }
.fact-list { margin: 0; }
.fact { display: grid; grid-template-columns: 138px minmax(0, 1fr); gap: 14px;
  padding: 10px 0; border-bottom: 1px solid var(--rule); }
.fact dt { color: var(--ink2); font-size: 11.5px; }
.fact dd { margin: 0; color: var(--ink1); font-size: 12.5px; overflow-wrap: anywhere; }
.fact dd a { text-decoration: none; }
.hash { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.disposition { padding: 16px; border: 1px dashed var(--rule2); border-radius: 10px; }
.disposition strong { display: block; font-size: 16px; }
.disposition p { margin: 5px 0 0; color: var(--ink2); font-size: 12.5px; }
.disposition-rule { height: 1px; margin: 14px 0; background: var(--rule2); }
.advisory-value { color: var(--brass); }
.nonclaims { margin: 17px 0 0; padding: 0; list-style: none; }
.nonclaims li { padding: 7px 0; border-bottom: 1px solid var(--rule); color: var(--ink1); font-size: 12.5px; }
.nonclaims li::before { content: "Not "; color: var(--cinnabar); font-weight: 680; }
.recurrence { display: flex; gap: 12px; align-items: flex-start; padding: 14px 0; }
.recurrence p { margin: 0; color: var(--ink1); }
.recurrence small { display: block; margin-top: 3px; color: var(--ink2); }
.method-intro { max-width: 72ch; margin: 26px 0 34px; font-size: 16px; color: var(--ink1); }
.loop { margin: 0; padding: 0; list-style: none; counter-reset: loop; }
.loop li { counter-increment: loop; display: grid; grid-template-columns: 34px minmax(0, 1fr);
  gap: 14px; padding: 17px 0; border-top: 1px solid var(--rule2); }
.loop li::before { content: counter(loop, decimal-leading-zero); color: var(--ink2);
  font: 680 12px/1.8 ui-monospace, SFMono-Regular, Menlo, monospace; }
.loop h3 { margin: 0 0 3px; font-size: 14px; }
.loop p { margin: 0; max-width: 72ch; color: var(--ink1); }
.method-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 38px; margin-top: 34px; }
.method-grid h3 { margin: 0 0 10px; font-size: 14px; }
.method-grid ul { margin: 0; padding-left: 18px; color: var(--ink1); }
.method-grid li { margin: 7px 0; }
@media (max-width: 600px) {
  .wrap { padding: 20px 14px 48px; }
  header { align-items: flex-start; flex-direction: column; gap: 8px; }
  .meta { margin-left: 0; }
  .audit-record-h { align-items: flex-start; flex-direction: column; gap: 8px; }
  .boundary { flex-direction: column; gap: 4px; }
  .controls { position: static; padding: 9px 0; }
  .controls-row { align-items: stretch; }
  .search, .search input { width: 100%; max-width: none; }
  .search input { min-height: 44px; }
  .filterbar { width: 100%; }
  .fbtn, .tab { min-height: 44px; }
  .tabs { width: 100%; order: 3; }
  .tab { padding-inline: 14px; }
  .count { align-self: center; }
  .spacer { display: none; }
  .view-intro { align-items: flex-start; flex-direction: column; gap: 4px; }
  .pilot-head h2 { font-size: 23px; }
  .evidence-row { grid-template-columns: 1fr; gap: 5px; }
  .pilot-split, .method-grid { grid-template-columns: 1fr; gap: 24px; }
  .fact { grid-template-columns: 1fr; gap: 3px; }
}

footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--rule);
  color: var(--ink2); font-size: 12px; line-height: 1.75; }
footer p { margin: 0 0 8px; max-width: 82ch; }
footer a { color: var(--ink1); text-decoration: none; border-bottom: 1px solid var(--rule2); }
footer a:hover { color: var(--accent); border-color: var(--accent); }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style></head>
<body><a class="skip" href="#app">Skip to content</a><div class="wrap">
<header>
  <h1><span class="product-name">Open Formal Workflows</span><span class="h1-sub">Formal Conjectures &middot; Review, Verification &amp; Preservation</span></h1>
  <div class="meta">Updated __STAMP__<span class="sep">|</span><a href="__LANDING_SITE__">overview</a><span class="sep">|</span><a href="__FC_REPO__/pulls">pull requests</a><span class="sep">|</span><a href="__FC_SITE__">formal-conjectures</a><span class="sep">|</span><a href="__BOARD_REPO__">source</a></div>
</header>
<div class="boundary"><strong>Advisory evidence only</strong><span>Formal Conjectures is canonical for declarations, pull requests, CI, and maintainer decisions. Board checks and reports never mean approval or merge acceptance. <a href="https://github.com/google-deepmind/formal-conjectures/issues/4394">Protocol&nbsp;#4394</a></span></div>
<div id="strip" class="strip"></div>
<div class="controls">
  <div class="controls-row">
    <div class="search">
      <svg class="s-icon" viewBox="0 0 256 256" aria-hidden="true"><path d="M229.66 218.34l-50.07-50.06a88.11 88.11 0 1 0-11.31 11.31l50.06 50.07a8 8 0 0 0 11.32-11.32ZM40 112a72 72 0 1 1 72 72 72.08 72.08 0 0 1-72-72Z"/></svg>
      <input id="search" type="search" placeholder="Search #, title, author" aria-label="Search pull requests">
    </div>
    <div class="filterbar" id="filterbar"></div>
    <div class="spacer"></div>
    <div class="tabs" id="tabs" role="tablist"></div>
    <span class="count" id="count"></span>
  </div>
</div>
<main id="app" tabindex="-1"></main>
<noscript><p class="empty">This board needs JavaScript to filter and render.
See the open pull requests at <a href="__FC_REPO__/pulls">github.com/google-deepmind/formal-conjectures</a>.</p></noscript>
<footer>
  __PR_AUDIT_NOTE__
  <p><strong>Queue labels are triage aids, not decisions.</strong> Ready for review means not draft, no changes requested, no merge conflict, and CI not failing. Approvals, CI, audit labels, and changed lines remain separate evidence.</p>
  <p>PR data comes from GitHub via queueboard; optional problem-audit data comes from the <a href="__FRONTIER__">Erd&#337;s frontier</a> snapshot. Open Formal Workflows is independent and not affiliated with Formal Conjectures maintainers. <a href="__METHOD__">Method and authority &rarr;</a></p>
</footer>
</div>
<script>
const DATA = __DATA__;
const PR_AUDITS = __PR_AUDITS__;
const PILOT = __PILOT__;
const ISSUES = __ISSUES__;
const META = __META__;

const AUDIT_LABEL = {signed:'signed', unconditional:'unconditional', conditional:'conditional', flagged:'flagged', unaudited:'unaudited'};
const AUDIT_ORDER = ['flagged','conditional','signed','unconditional','unaudited'];
const CLS_OF = {signed:'ab--signed', unconditional:'ab--unconditional', conditional:'ab--conditional', flagged:'ab--discrepancy', unaudited:'ab--unaudited'};
const AUDIT_DOT = {signed:'gold', unconditional:'moss', conditional:'brass', flagged:'cinnabar', unaudited:'stone'};
const CARET = '<svg width="9" height="9" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const FID_TITLE = {flagged:'Flagged unfaithful', conditional:'Conditional: rests on an assumption', signed:'Signed faithful', unconditional:'Machine-checked unconditional', unaudited:'Not yet audited'};
const BUCKETS = [['review','Ready for review'],['approved','Approval recorded'],['author','Waiting on the author'],['draft','Draft or work in progress']];
const COLS = [['n','PR'],['title','Title'],['author','Author'],['kind','Kind'],['prAudit','PR audit'],['audit','Proof audit'],['age','Open age'],['waiting','Queue wait'],['idle','Idle'],['ci','CI'],['appr','Approvals'],['churn','Lines']];
const COLUMNS = COLS.filter(c => (c[0] !== 'audit' || META.hasAudit) && (c[0] !== 'prAudit' || META.hasPrAudit));
const SORTABLE = {n:1, author:1, audit:1, age:1, waiting:1, idle:1, ci:1, appr:1, churn:1};
// Only offer collections that are actually present, so the menu reflects the
// queue rather than the repo's full label list.
const COLLECTIONS = [...new Set(DATA.flatMap(r => r.coll))].sort();
const FACETS = [
  {group:'audit', label:'Audit', opts:['signed','unconditional','conditional','flagged','unaudited']},
  {group:'kind', label:'Kind', opts:['statement','infra']},
  {group:'coll', label:'Collection', opts:COLLECTIONS},
  {group:'ci', label:'CI', opts:['passing','failing','pending','running']},
];

const DEFAULT_VIEW = 'queue';
const TAB_SPECS = [['queue','Review queue'],['pilot','Contribution evidence'],['all','All open PRs'],['pick','Find a case'],['fidelity','Fidelity'],['pr-audits','Evidence'],['method','Method']]
  .filter(v => (v[0] !== 'pilot' && v[0] !== 'method' || META.hasPilot)
            && (v[0] !== 'fidelity' || META.hasAudit)
            && (v[0] !== 'pick' || META.hasIssues)
            && (v[0] !== 'pr-audits' || META.hasPrAuditFeed));
const DATA_VIEWS = new Set(['queue','all','pick','fidelity']);
const state = {view:DEFAULT_VIEW, q:'', facets:{audit:new Set(), kind:new Set(), coll:new Set(), ci:new Set()}, sort:{col:'idle', dir:'desc'}};

const el = id => document.getElementById(id);
const app = el('app'), searchEl = el('search'), filterbarEl = el('filterbar'), tabsEl = el('tabs'), countEl = el('count');
function esc(s){ const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
function ciKey(r){ return r.ci === 'green' ? 'passing' : r.ci === 'failing' ? 'failing' : r.ci === 'running' ? 'running' : 'pending'; }

function matches(r){
  if (state.q){ const q = state.q.toLowerCase();
    if (!(('#'+r.n).includes(q) || r.title.toLowerCase().includes(q) || r.author.toLowerCase().includes(q))) return false; }
  const f = state.facets;
  if (f.audit.size && !r.auditStatuses.some(s => f.audit.has(s))) return false;
  if (f.kind.size && !f.kind.has(r.kind)) return false;
  if (f.coll.size && !r.coll.some(c => f.coll.has(c))) return false;
  if (f.ci.size && !f.ci.has(ciKey(r))) return false;
  return true;
}

function badge(a){ return '<a class="ab '+a.cls+'" href="'+a.href+'" title="#'+a.n+': '+esc(a.note)+'">'+a.n+'</a>'; }
function auditCell(r){
  if (!r.audit.length) return '<td class="audit"></td>';
  if (r.audit.length <= 4) return '<td class="audit">'+r.audit.map(badge).join('')+'</td>';
  const counts = {}; r.audit.forEach(a => counts[a.status] = (counts[a.status]||0)+1);
  const order = AUDIT_ORDER.filter(s => counts[s]);
  const chips = order.map(s => '<span class="rc '+CLS_OF[s]+'">'+counts[s]+'</span>').join('');
  const title = r.audit.length+' problems: '+order.map(s => counts[s]+' '+AUDIT_LABEL[s]).join(', ');
  return '<td class="audit"><span class="roll" title="'+title+'"><b>'+r.audit.length+'</b>'+chips+'</span></td>';
}
function prAuditCell(r){
  if (!r.prAudit) return '<td class="audit"></td>';
  const d = r.prAudit.advisory_disposition;
  return '<td class="audit"><a class="ab pa pa--'+d+'" href="'+r.prAudit.source_url+'" title="Inspect the exact advisory FC audit record; not approval or authority">'+d.replaceAll('_', ' ')+'</a></td>';
}
function flagsHtml(r){ let s = '';
  // A tick from months ago was earned against a main that has moved since.
  // Reported as an age, not as a verdict: the reviewer decides what it means.
  if (r.ciAge != null && r.ciAge >= 30) s += '<span class="flag flag--stale" title="checks last ran '
    + r.ciAge + ' days ago, against an older main">CI ' + (r.ciAge >= 60 ? Math.round(r.ciAge/30) + 'mo' : r.ciAge + 'd') + ' old</span>';
  if (r.who && r.who.length) s += '<span class="flag flag--who" title="assigned to '
    + r.who.join(', ') + '">' + esc(r.who[0]) + (r.who.length > 1 ? ' +' + (r.who.length - 1) : '') + '</span>';
  if (r.onMain) s += '<span class="flag flag--onmain" title="Every file this PR adds is already on the base branch, so the work may have landed another way. A prompt to check, not a verdict: the data cannot tell an added file from one that was only appended to.">already on main?</span>';
  if (r.staleWhy) s += '<span class="flag flag--rebase" title="'+esc(r.staleWhy)+'">needs rebase</span>';
  if ((r.contributionEvidence || []).length) s += '<a class="flag" href="#view=pilot">'+r.contributionEvidence.length+' evidence records</a>';
  if (r.ciPending) s += '<span class="flag flag--ci" title="CI has not run yet (often waiting on a maintainer to approve the workflow)">CI pending</span>';
  if (r.conflict) s += '<span class="flag flag--conflict" title="Merge conflict with the base branch">conflict</span>';
  return s; }
function ciDot(r){ const m = {green:'ok', failing:'bad', running:'run', none:'na'}; return '<span class="ci ci--'+m[r.ci]+'" title="'+r.ci+'"></span>'; }
function rowHtml(r){
  const appr = r.appr ? '<span class="appr">&check;'+r.appr+'</span>' : '';
  return '<tr>'
    + '<td class="num"><a href="https://github.com/'+META.repo+'/pull/'+r.n+'">#'+r.n+'</a></td>'
    + '<td class="ttl"><span class="ttl-t">'+esc(r.title)+'</span>'+flagsHtml(r)+'</td>'
    + '<td class="who">'+esc(r.author)+'</td>'
    + '<td><span class="tag tag--'+r.kind+'">'+r.kind+'</span></td>'
    + (META.hasPrAudit ? prAuditCell(r) : '')
    + (META.hasAudit ? auditCell(r) : '')
    + '<td class="mono">'+r.age+'d</td>'
    + '<td class="mono" title="time actually spent on the review queue">'+(r.waiting == null ? '<span class="dash">&mdash;</span>' : r.waiting+'d')+'</td>'
    + '<td class="mono">'+r.idle+'d</td>'
    + '<td>'+ciDot(r)+'</td><td class="mono appr-c">'+appr+'</td><td class="mono">'+r.churn+'</td>'
    + '</tr>';
}

const AUDIT_RANK = {'ab--discrepancy':0, 'ab--conditional':1, 'ab--variant':1, 'ab--signed':2, 'ab--unconditional':3};
function auditRank(r){ return r.auditTop != null ? AUDIT_RANK[r.auditTop] : (r.audit.length ? 4 : 5); }
function sortVal(r, col){
  if (col === 'audit') return auditRank(r);
  if (col === 'waiting') return r.waiting == null ? -1 : r.waiting;
  if (col === 'ci'){ return {failing:0, running:1, none:2, green:3}[r.ci]; }
  return r[col];
}
function sortRecs(recs){ const {col, dir} = state.sort, m = dir === 'asc' ? 1 : -1;
  return recs.slice().sort((a, b) => { const x = sortVal(a, col), y = sortVal(b, col);
    return typeof x === 'string' ? m*x.localeCompare(y) : m*(x - y); }); }

function tableHtml(recs, sortable){
  const head = COLUMNS.map(([k, l]) => {
    const s = sortable && SORTABLE[k], cur = state.sort.col === k;
    const arrow = cur ? '<span class="caret'+(state.sort.dir === 'asc' ? ' up' : '')+'">'+CARET+'</span>' : '';
    return s ? '<th class="sortable'+(cur?' active':'')+'"><button class="sorter" data-col="'+k+'" aria-label="Sort by '+k+'">'+l+arrow+'</button></th>' : '<th>'+l+'</th>';
  }).join('');
  return '<div class="scroll"><table class="pr-table"><thead><tr>'+head+'</tr></thead><tbody>'+recs.map(rowHtml).join('')+'</tbody></table></div>';
}
function emptyState(msg){ return '<div class="empty">'+(msg||'No pull requests match these filters.')+' <button class="linkish" data-reset>Clear filters</button></div>'; }

function renderQueue(recs){
  const out = BUCKETS.map(([b, title]) => {
    const g = recs.filter(r => r.bucket === b); if (!g.length) return '';
    const key = r => r.waiting != null ? r.waiting : r.age;
    const sorted = b === 'review' ? g.slice().sort((a, b2) => key(b2) - key(a)) : g.slice().sort((a, b2) => b2.idle - a.idle);
    return '<section><div class="sec-h"><h2>'+title+'</h2><span class="n">'+g.length+'</span></div>'+tableHtml(sorted, false)+'</section>';
  }).join('');
  if (!out) return emptyState();
  return '<div class="view-intro"><h2>Formal Conjectures review queue</h2><p>Scan what is ready, then open the upstream pull request for every authoritative review or maintainer action.</p></div>'+out;
}
function renderAll(recs){ return recs.length ? '<section>'+tableHtml(sortRecs(recs), true)+'</section>' : emptyState(); }
// Conjectures nothing blocks and nobody has started: `new conjecture` without
// `needs-prerequisites`, minus the ones an open PR already says it closes. That last part is
// the whole point of showing this here rather than linking to the issue list, which cannot
// see the pull requests.
function renderPick(){
  const q = (state.q || '').toLowerCase();
  const all = ISSUES.filter(i => i.ready && (!q || i.title.toLowerCase().includes(q)));
  const byAge = (a, b) => b.age - a.age;
  const free = all.filter(i => !i.prs.length && !i.have).sort(byAge);
  const taken = all.filter(i => i.prs.length).sort(byAge);
  const done = all.filter(i => !i.prs.length && i.have).sort(byAge);
  if (!all.length) return emptyState();
  const row = i => '<tr><td class="num"><a href="https://github.com/' + META.repo + '/issues/' + i.n + '">#' + i.n + '</a></td>'
    + '<td class="ti">' + esc(i.title) + '</td><td class="muted">' + esc(i.ams) + '</td>'
    + '<td class="num">' + i.age + 'd</td><td>'
    + (i.have ? '<a class="flag flag--onmain" href="https://github.com/' + META.repo + '/blob/main/' + i.have + '">in repo</a>' : '')
    + i.prs.map(n => '<a class="flag flag--onmain" href="https://github.com/' + META.repo + '/pull/' + n + '">#' + n + '</a>').join(' ')
    + '</td></tr>';
  const table = rows => '<table><thead><tr><th>issue</th><th>title</th><th>area</th><th>open</th><th>PR</th></tr></thead><tbody>'
    + rows.map(row).join('') + '</tbody></table>';
  return '<section><p class="muted">' + free.length + ' conjectures with no missing prerequisites and no open PR, oldest first.</p>'
    + table(free)
    + (taken.length ? '<p class="muted" style="margin-top:2rem">' + taken.length
        + ' more are already claimed by an open pull request.</p>' + table(taken) : '')
    + (done.length ? '<p class="muted" style="margin-top:2rem">' + done.length
        + ' already exist in the repository and the issue was never closed.</p>' + table(done) : '')
    + '</section>';
}

function renderFidelity(recs){
  const byProblem = {};
  recs.forEach(r => r.audit.forEach(a => { (byProblem[a.n] || (byProblem[a.n] = {n:a.n, cls:a.cls, status:a.status, note:a.note, href:a.href, prs:[]})).prs.push(r); }));
  const probs = Object.values(byProblem);
  if (!probs.length) return emptyState('No audited Erdős-problem PRs match.');
  const sel = state.facets.audit;  // in this view the audit facet selects problem groups directly
  const groups = AUDIT_ORDER.map(s => [s, probs.filter(p => p.status === s).sort((a, b) => a.n - b.n)])
    .filter(g => g[1].length && (!sel.size || sel.has(g[0])));
  return groups.map(([s, ps]) => '<section><div class="sec-h"><h2>'+FID_TITLE[s]+'</h2><span class="n">'+ps.length+'</span></div>'
    + '<div class="scroll"><table><thead><tr><th>problem</th><th>audit</th><th>open PRs</th></tr></thead><tbody>'
    + ps.map(p => '<tr><td class="num"><a href="'+p.href+'">#'+p.n+'</a></td>'
        + '<td><span class="ab '+p.cls+'" title="#'+p.n+': '+esc(p.note)+'">'+AUDIT_LABEL[p.status]+'</span></td>'
        + '<td>'+p.prs.map(r => '<a class="prlink" href="https://github.com/'+META.repo+'/pull/'+r.n+'" title="'+esc(r.title)+'">#'+r.n+'</a>').join('')+'</td></tr>').join('')
    + '</tbody></table></div></section>').join('');
}

function renderPrAudits(){
  if (!PR_AUDITS.length) return emptyState('No exact per-PR audit records are configured.');
  const rows = PR_AUDITS.map(r => {
    const pr = r.pull_request;
    const checks = r.checks.map(c => '<li><code>'+esc(c.id)+'</code> &middot; '
      +esc(c.property)+' &middot; <strong>'+esc(c.outcome)+'</strong>'
      +(c.severity === 'none' ? '' : ' &middot; '+esc(c.severity))+'</li>').join('');
    return '<article class="audit-record"><div class="audit-record-h"><div><a class="num" href="'+pr.url+'">#'+pr.number+'</a> '
      +'<a href="'+r.source_url+'"><strong>'+esc(r.fixture)+'</strong></a></div>'
      +'<span class="ab pa pa--'+r.advisory_disposition+'">'+r.advisory_disposition.replaceAll('_',' ')+'</span></div>'
      +'<ul>'+checks+'</ul><p class="muted mono">core '+esc(r.core.root)+'<br>observation '+esc(r.observation.root)+'</p></article>';
  }).join('');
  return '<section><div class="sec-h"><h2>Exact per-PR audit records</h2><span class="n">'+PR_AUDITS.length+'</span></div>'
    +'<p class="muted">Five commit-pinned advisory fixtures. They do not establish approval, merge readiness, mathematical truth, Decision, or Standing.</p>'
    +'<div class="audit-records">'+rows+'</div></section>';
}

function humanize(value){ return String(value == null ? '' : value).replaceAll('_', ' '); }
function outcome(value){
  const cls = value === 'pass' || value === 'current' ? 'pass' : value === 'error' || value === 'stale' ? 'error' : 'pending';
  return '<span class="outcome outcome--'+cls+'">'+esc(humanize(value))+'</span>';
}
function evidenceRow(name, source, detail, result){
  return '<div class="evidence-row"><div class="evidence-name">'+esc(name)+'</div>'
    +'<div class="evidence-source">'+source+'<small>'+esc(detail)+'</small></div>'+outcome(result)+'</div>';
}
function fact(label, value){ return '<div class="fact"><dt>'+esc(label)+'</dt><dd>'+value+'</dd></div>'; }
function hash(value){ return '<span class="hash">'+esc(value)+'</span>'; }

function renderPilot(){
  if (!PILOT) return emptyState('Contribution evidence is not configured.');
  const intro = '<p>Validated toolkit records. Artifact integrity does not establish mathematical correctness or maintainer acceptance.</p>';
  if (!PILOT.runs.length) return intro + emptyState(PILOT.message || (PILOT.status === 'no_records' ? 'No published records.' : 'Evidence: '+PILOT.status));
  return intro + PILOT.runs.map(run => {
    const summary=run.summary, target=run.target || {};
    const url=run.url && /^https:\/\/github\.com\//.test(run.url) ? run.url : null;
    const findings=(summary.findings || []).map(f => '<li>'+esc(f.file)+':'+esc(String(f.line))+' — '+esc(f.message)+'</li>').join('');
    return '<article class="pilot"><header class="pilot-head"><h2>'+esc(target.declaration || 'PR #'+target.pr)+'</h2>'
      +'<p>'+esc(summary.semantic_verdict || run.outcome)+' · '+esc(run.applicability)+' · '+esc(run.producer)+'</p></header>'
      +'<dl class="fact-list">'+fact('Run',esc(run.id))+fact('Reviewed revision',hash(target.head || target.commit || 'unknown'))
      +fact('Observed',esc(run.applicability_observed_at || 'not observed'))
      +fact('Changes',esc((run.changes || []).join(', ') || 'none observed'))+'</dl>'
      +(findings ? '<ul>'+findings+'</ul>' : '')
      +'<p>Coverage gaps: '+esc((summary.gaps || []).join('; ') || 'none reported')+'</p>'
      +(run.kind === 'verify' ? '<p>Policy: '+esc(summary.policy_outcome || (['pass','rejected'].includes(summary.comparator?.outcome) ? summary.comparator.outcome : 'not_evaluated'))+'</p>' : '')
      +(url ? '<p><a href="'+esc(url)+'">Inspect immutable evidence</a></p>' : '')
      +(summary.reviewer ? '<p>Reviewer: '+esc(summary.reviewer)+'</p>' : '')
      +(summary.reviewer_attributions?.record?.reviewers || []).map(reviewer => '<p>Attributed reviewer: '+esc(reviewer.name)+' ('+esc(reviewer.kind)+', self-reported). Shared context: '+esc(reviewer.shared_dependencies.join(', ') || 'none reported')+'</p>').join('')
      +((run.fc_pages || []).length ? '<p>'+run.fc_pages.map(page => '<a href="'+esc(page.url)+'">'+esc(page.path)+'</a>').join(' · ')+'</p>' : '<p><a href="__FC_SITE__">Browse FC statements</a></p>')
      +'<pre><code>'+esc(target.declaration ? "conjectures show '"+target.declaration.replaceAll("'", "'\\''")+"'" : 'conjectures review --pr '+target.pr)+'</code></pre></article>';
  }).join('');
}

function renderMethod(){
  return '<article><h2>Review, verification, and preservation</h2><p>The FC toolkit validates and assembles evidence. This board displays its records alongside queueboard timing and GitHub state.</p><p>Results retain exact inputs and producer attribution. Current observations can make a result historical; they never reinterpret it as a different mathematical outcome. Maintainers decide acceptance.</p><p><a href="https://github.com/google-deepmind/formal-conjectures/issues/4394">Roadmap</a> · <a href="https://github.com/williamjblair/open-formal-workflows/tree/3300a105864c34ed97ad30a182496b3d570e0039/pilot">Historical #4884 evidence</a></p></article>';
}

function statHtml(v, l, cls, facet){
  const body = '<span class="sv '+(cls||'')+'">'+v+'</span> <span class="sl">'+l+'</span>';
  if (!facet) return '<div class="stat">'+body+'</div>';
  const on = state.facets.audit.has(facet);
  return '<button type="button" class="stat stat--go'+(on ? ' is-on' : '')+'" data-audit="'+facet
    + '" aria-pressed="'+on+'" title="Show only '+l+'">'+body+'</button>';
}
function renderStrip(){
  const review = DATA.filter(r => r.bucket === 'review');
  const stmt = review.filter(r => r.kind === 'statement').length;
  // Consistent with the waiting column: time on the queue, age as fallback.
  const oldest = review.reduce((m, r) => Math.max(m, r.waiting != null ? r.waiting : r.age), 0);
  let html = '<div class="grp">'+statHtml(DATA.length,'open')+statHtml(review.length,'ready to review')+statHtml(stmt,'statements')+statHtml(oldest+'d','oldest waiting')+'</div>';
  // Signed-faithful and conditional counts used to sit here. At 1 and 3 against
  // 146 PRs they cost a third of the header for a signal nobody acts on; the
  // per-row chips and the Fidelity view carry that detail already. A signed
  // *unfaithful* proof is different in kind, so it appears only when there is
  // one, which is the only time it means anything.
  if (META.hasAudit){
    const top = DATA.filter(r => r.bucket === 'review' || r.bucket === 'approved').map(r => r.auditTop);
    const flagged = top.filter(x => x === 'ab--discrepancy').length;
    if (flagged) html += '<div class="grp grp--audit">'
      + statHtml(flagged, 'flagged by the audit', 'sv--cinnabar', 'flagged') + '</div>';
  }
  el('strip').innerHTML = html;
  el('strip').querySelectorAll('.stat--go').forEach(b => b.addEventListener('click', () => {
    const set = state.facets.audit, v = b.dataset.audit;
    set.has(v) ? set.delete(v) : set.add(v);
    syncUrl(); updateFilterUI(); render(); renderStrip();
  }));
}

function render(){
  const recs = DATA.filter(matches);
  if (DATA_VIEWS.has(state.view)) countEl.textContent = recs.length === DATA.length ? DATA.length+' PRs' : recs.length+' of '+DATA.length+' PRs';
  app.innerHTML = state.view === 'pilot' ? renderPilot()
    : state.view === 'method' ? renderMethod()
    : state.view === 'queue' ? renderQueue(recs)
    : state.view === 'pick' ? renderPick()
    : state.view === 'fidelity' ? renderFidelity(recs)
    : state.view === 'pr-audits' ? renderPrAudits() : renderAll(recs);
  app.querySelectorAll('button.sorter').forEach(button => button.addEventListener('click', () => {
    const c = button.dataset.col;
    if (state.sort.col === c) state.sort.dir = state.sort.dir === 'asc' ? 'desc' : 'asc';
    else { state.sort.col = c; state.sort.dir = c === 'author' ? 'asc' : 'desc'; }
    syncUrl(); render();
  }));
  app.querySelectorAll('[data-reset]').forEach(b => b.addEventListener('click', resetAll));
}
function updateTabs(){ tabsEl.querySelectorAll('.tab').forEach(b => {
  const active = b.dataset.view === state.view;
  b.classList.toggle('active', active); b.setAttribute('aria-selected', active); b.tabIndex = active ? 0 : -1;
}); }
function updateViewChrome(){
  const dataView = DATA_VIEWS.has(state.view);
  searchEl.closest('.search').hidden = !dataView;
  filterbarEl.hidden = !dataView;
  countEl.hidden = !dataView;
  el('strip').hidden = state.view === 'pilot' || state.view === 'method' || state.view === 'pr-audits';
}

function closeMenus(){ filterbarEl.querySelectorAll('.fdd.open').forEach(dd => {
  dd.classList.remove('open'); dd.querySelector('.fmenu').hidden = true;
  dd.querySelector('.fbtn').setAttribute('aria-expanded', 'false'); }); }
function updateFilterUI(){
  filterbarEl.querySelectorAll('.fdd').forEach(dd => {
    const g = dd.dataset.group, n = state.facets[g].size;
    dd.querySelector('.fbtn').classList.toggle('active', n > 0);
    dd.querySelector('.fbtn-n').textContent = n ? ' ' + n : '';
    dd.querySelectorAll('.fopt input').forEach(cb => cb.checked = state.facets[g].has(cb.value));
  });
  const any = state.q || ['audit','kind','coll','ci'].some(g => state.facets[g].size);
  const cb = el('clearBtn'); if (cb) cb.hidden = !any;
}

function buildToolbar(){
  tabsEl.innerHTML = TAB_SPECS
    .map(([k, l]) => '<button class="tab" role="tab" data-view="'+k+'">'+l+'</button>').join('');
  tabsEl.querySelectorAll('.tab').forEach(b => b.addEventListener('click', () => { state.view = b.dataset.view; syncUrl(); updateTabs(); updateViewChrome(); renderStrip(); render(); }));
  tabsEl.addEventListener('keydown', event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    const tabs = [...tabsEl.querySelectorAll('.tab')], current = tabs.indexOf(document.activeElement);
    if (current < 0) return;
    let next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
      : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    event.preventDefault(); tabs[next].focus(); tabs[next].click();
  });
  const groups = FACETS.filter(f => f.group !== 'audit' || META.hasAudit);
  filterbarEl.innerHTML = groups.map(f =>
    '<div class="fdd" data-group="'+f.group+'"><button class="fbtn" type="button" aria-haspopup="true" aria-expanded="false">'
    + f.label + '<span class="fbtn-n"></span>' + CARET + '</button><div class="fmenu" role="menu" hidden>'
    + f.opts.map(o => { const dot = f.group === 'audit' ? '<span class="cdot cdot--'+AUDIT_DOT[o]+'"></span>' : '';
        return '<label class="fopt"><input type="checkbox" data-group="'+f.group+'" value="'+o+'">'+dot+'<span>'+o+'</span></label>'; }).join('')
    + '</div></div>').join('') + '<button class="clear-btn" id="clearBtn" type="button" hidden>Clear all</button>';
  filterbarEl.querySelectorAll('.fbtn').forEach(btn => btn.addEventListener('click', e => {
    e.stopPropagation(); const dd = btn.closest('.fdd'); const open = dd.classList.contains('open'); closeMenus();
    if (!open){ dd.classList.add('open'); dd.querySelector('.fmenu').hidden = false; btn.setAttribute('aria-expanded', 'true'); } }));
  filterbarEl.querySelectorAll('.fmenu').forEach(m => m.addEventListener('click', e => e.stopPropagation()));
  filterbarEl.querySelectorAll('.fopt input').forEach(cb => cb.addEventListener('change', () => {
    const set = state.facets[cb.dataset.group]; cb.checked ? set.add(cb.value) : set.delete(cb.value);
    syncUrl(); updateFilterUI(); render(); }));
  el('clearBtn').addEventListener('click', resetAll);
  searchEl.addEventListener('input', () => { state.q = searchEl.value.trim(); syncUrl(); updateFilterUI(); render(); });
  document.addEventListener('click', closeMenus);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenus(); });
}
function resetAll(){ state.q = ''; searchEl.value = '';
  state.facets = {audit:new Set(), kind:new Set(), coll:new Set(), ci:new Set()}; closeMenus(); syncUrl(); updateFilterUI(); render(); }

function syncUrl(){
  const p = new URLSearchParams();
  if (state.view !== DEFAULT_VIEW) p.set('view', state.view);
  if (state.q) p.set('q', state.q);
  ['audit','kind','coll','ci'].forEach(g => { if (state.facets[g].size) p.set(g, [...state.facets[g]].join(',')); });
  if (state.view === 'all') p.set('sort', state.sort.col+':'+state.sort.dir);
  const h = p.toString();
  history.replaceState(null, '', h ? '#'+h : location.pathname + location.search);
}
function loadUrl(){
  const p = new URLSearchParams(location.hash.slice(1));
  if (p.get('view') && TAB_SPECS.some(v => v[0] === p.get('view'))) state.view = p.get('view');
  if (p.get('q')){ state.q = p.get('q'); searchEl.value = state.q; }
  ['audit','kind','coll','ci'].forEach(g => { if (p.get(g)) state.facets[g] = new Set(p.get(g).split(',')); });
  if (p.get('sort')){ const s = p.get('sort').split(':'); state.sort = {col:s[0], dir:s[1] || 'desc'}; }
}

renderStrip();
buildToolbar();
loadUrl();
updateTabs();
updateViewChrome();
updateFilterUI();
render();
</script>
</body></html>
"""


if __name__ == "__main__":
    main()
