from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import fc_pr_audit
import generate


class FcPrAuditProjectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = os.environ.get("FC_PR_AUDIT_SOURCE")
        if not source:
            raise RuntimeError(
                "FC_PR_AUDIT_SOURCE must name the exact public audit checkout"
            )
        cls.source = Path(source)
        cls.projection = fc_pr_audit.build_projection(cls.source)

    def test_exact_five_case_outcomes_are_preserved(self) -> None:
        rows = {row["pull_request"]["number"]: row for row in self.projection["rows"]}
        self.assertEqual(
            {number: row["advisory_disposition"] for number, row in rows.items()},
            {
                1237: "needs_revision",
                3959: "unavailable",
                4830: "needs_revision",
                4829: "clean",
                4884: "inconclusive",
            },
        )
        self.assertEqual(self.projection["authority_effect"], "none")
        self.assertEqual(
            self.projection["coverage"],
            {"complete": True, "expected": 5, "observed": 5},
        )
        self.assertEqual(
            self.projection["root"],
            "sha256:70795b9827c773958718ff8cbd9a63d7e25bf439db70b7bafcbe3da1c65678ca",
        )

    def test_clean_source_fidelity_and_unavailable_remain_non_authoritative(self) -> None:
        rows = {row["pull_request"]["number"]: row for row in self.projection["rows"]}
        self.assertEqual(rows[4829]["advisory_disposition"], "clean")
        self.assertIn("source-statement-fidelity", rows[4829]["basis_check_ids"])
        self.assertIn("not_a_repository_decision_or_standing", rows[4829]["nonclaims"])
        self.assertEqual(rows[3959]["advisory_disposition"], "unavailable")
        outcomes = {check["outcome"] for check in rows[3959]["checks"]}
        self.assertIn("unavailable", outcomes)
        self.assertNotIn("error", outcomes)
        self.assertNotIn("fail", outcomes)

    def test_projection_refuses_outcome_and_completeness_drift(self) -> None:
        changed = json.loads(json.dumps(self.projection))
        changed["rows"][0]["advisory_disposition"] = "clean"
        with self.assertRaisesRegex(fc_pr_audit.ProjectionError, "outcome"):
            fc_pr_audit.validate_projection(changed)
        changed = json.loads(json.dumps(self.projection))
        changed["coverage"]["observed"] = 4
        with self.assertRaisesRegex(fc_pr_audit.ProjectionError, "completeness"):
            fc_pr_audit.validate_projection(changed)

    def test_projection_refuses_record_and_basis_drift(self) -> None:
        changed = json.loads(json.dumps(self.projection))
        changed["rows"][0]["core"]["root"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(fc_pr_audit.ProjectionError, "record binding"):
            fc_pr_audit.validate_projection(changed)
        changed = json.loads(json.dumps(self.projection))
        changed["rows"][0]["basis_check_ids"] = ["not-a-retained-check"]
        with self.assertRaisesRegex(fc_pr_audit.ProjectionError, "disposition basis"):
            fc_pr_audit.validate_projection(changed)
        changed = json.loads(json.dumps(self.projection))
        changed["rows"][0]["checks"][0]["property"] = "changed-property"
        changed_without_root = {
            key: value for key, value in changed.items() if key != "root"
        }
        changed["root"] = fc_pr_audit._content_root(changed_without_root)
        with self.assertRaisesRegex(fc_pr_audit.ProjectionError, "row root"):
            fc_pr_audit.validate_projection(changed)

    def test_hosted_workflow_uses_exact_sources_and_action_pins(self) -> None:
        workflow = (Path(__file__).parent / ".github/workflows/board.yml").read_text()
        self.assertRegex(workflow, r"formal-conjectures\.git@[0-9a-f]{40}")
        self.assertIn("python3 shared_records.py", workflow)
        self.assertNotIn("python3 -B fc_pr_audit.py", workflow)
        self.assertNotIn("python3 -B review_report.py", workflow)
        self.assertIn("astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86", workflow)
        self.assertIn("actions/deploy-pages@d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e", workflow)
        self.assertNotRegex(workflow, r"uses:\s+[^\s]+@v\d")

    def test_board_consumer_preserves_the_exact_pr_outcome(self) -> None:
        audits = {row["pull_request"]["number"]: row for row in self.projection["rows"]}
        record = generate.build_record(
            4884,
            {
                "title": "Conditional proof",
                "author": "fixture",
                "pr_status": "AwaitingReview",
                "ci_status": "pass",
                "modified_files": [],
                "labels": [],
                "approvals": [],
                "assignees": [],
                "additions": 1,
                "deletions": 0,
                "total_queue_time": {"status": "valid", "value_td": 86400},
                "last_status_change": {"status": "valid", "delta": {"days": 1}},
            },
            {"createdAt": "2026-08-01T00:00:00Z", "mergeStateStatus": "CLEAN"},
            {},
            audits,
            set(),
            datetime(2026, 8, 12, tzinfo=timezone.utc),
            set(),
        )
        self.assertEqual(record["prAudit"]["advisory_disposition"], "inconclusive")
        self.assertEqual(
            record["prAudit"]["core"]["root"],
            fc_pr_audit.FIXTURES["conditional-erdos-427-4884"]["core_root"],
        )

    def test_projection_is_byte_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            one = Path(tmp) / "one.json"
            two = Path(tmp) / "two.json"
            payload = (
                json.dumps(
                    self.projection,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            one.write_text(payload)
            again = fc_pr_audit.build_projection(self.source)
            two.write_text(
                json.dumps(
                    again, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                + "\n"
            )
            self.assertEqual(one.read_bytes(), two.read_bytes())


if __name__ == "__main__":
    unittest.main()
