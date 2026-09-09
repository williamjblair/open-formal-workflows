from __future__ import annotations

import unittest

import generate


class ReviewerWorkbenchContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.template = generate.TEMPLATE

    def test_recovered_workbench_is_queue_first(self) -> None:
        self.assertIn("const DEFAULT_VIEW = 'queue'", self.template)
        for tab in (
            "['queue','Review queue']",
            "['pilot','Contribution evidence']",
            "['all','All open PRs']",
            "['pick','Find a case']",
            "['pr-audits','Evidence']",
            "['method','Method']",
        ):
            self.assertIn(tab, self.template)
        self.assertIn("Formal Conjectures review queue", self.template)
        self.assertIn("open the upstream pull request", self.template)
        self.assertIn('<a href="__LANDING_SITE__">overview</a>', self.template)
        self.assertIn('href="../assets/favicon.svg"', self.template)

    def test_queue_keeps_information_rich_tables_and_filters(self) -> None:
        self.assertIn('class="scroll"><table class="pr-table"', self.template)
        self.assertIn('id="search" type="search"', self.template)
        self.assertIn('id="filterbar"', self.template)
        for label in (
            "['n','PR']",
            "['prAudit','PR audit']",
            "['audit','Proof audit']",
            "['waiting','Queue wait']",
            "['appr','Approvals']",
            "['churn','Lines']",
        ):
            self.assertIn(label, self.template)

    def test_ready_work_appears_before_approval_history(self) -> None:
        self.assertLess(
            self.template.index("['review','Ready for review']"),
            self.template.index("['approved','Approval recorded']"),
        )

    def test_authority_and_accessibility_boundaries_remain_explicit(self) -> None:
        self.assertIn("Advisory evidence only", self.template)
        self.assertIn("Formal Conjectures is canonical", self.template)
        self.assertIn("never mean approval or merge acceptance", self.template)
        self.assertNotIn('aria-live="polite"', self.template)
        self.assertIn(".fbtn, .tab { min-height: 44px; }", self.template)
        self.assertIn(".search input { min-height: 44px; }", self.template)
        self.assertIn("main:focus { outline: none; }", self.template)



if __name__ == "__main__":
    unittest.main()
