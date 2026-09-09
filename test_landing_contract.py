from __future__ import annotations

import unittest
from pathlib import Path

import generate


HERE = Path(__file__).parent


class PublicLandingContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.page = (HERE / "landing.html").read_text()
        self.workflow = (HERE / ".github/workflows/board.yml").read_text()

    def test_root_orients_and_opens_the_real_workbench(self) -> None:
        self.assertIn("Open Formal Workflows", self.page)
        self.assertIn("Evidence that stays evidence. Decisions that stay human.", self.page)
        self.assertGreaterEqual(self.page.count('href="./workbench/"'), 4)
        self.assertIn("Open the review workbench", self.page)
        self.assertIn('src="./assets/workbench-preview.jpg"', self.page)
        self.assertIn('srcset="./assets/workbench-preview-mobile.jpg"', self.page)
        self.assertIn("Open Formal Workflows review queue with grouped pull requests", self.page)
        self.assertTrue((HERE / "assets/workbench-preview.jpg").is_file())
        self.assertTrue((HERE / "assets/workbench-preview-mobile.jpg").is_file())
        self.assertIn('href="./assets/favicon.svg"', self.page)
        self.assertTrue((HERE / "assets/favicon.svg").is_file())

    def test_landing_preserves_authority_and_program_boundaries(self) -> None:
        for statement in (
            "First source-owned deployment:",
            "Formal Conjectures remains canonical and decisive",
            "LeanEval and Comparator bind runs to exact inputs",
            "Vela Protocol 1 is the technical substrate",
            "problems.science",
            "It is not a current integration or represented partner",
            "No maintainer endorsement or merge readiness is claimed",
            "Maintainer decisions remain outside the generated evidence.",
        ):
            self.assertIn(statement, self.page)

    def test_evidence_flow_is_ordered_and_honest(self) -> None:
        labels = (
            "Formal Conjectures source",
            "Pinned Lean execution",
            "Evidence review",
            "Maintainer records decision",
        )
        positions = [self.page.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("without creating authority", self.page)
        self.assertIn("Only the source maintainer can decide acceptance", self.page)

    def test_artifact_links_are_verified_public_routes(self) -> None:
        for href in (
            './workbench/#view=method',
            "https://github.com/google-deepmind/formal-conjectures/issues/4394",
            "https://github.com/vela-science/vela/blob/main/docs/PROTOCOL.md",
            "https://problems.science/",
            "https://github.com/williamjblair/open-formal-workflows",
        ):
            self.assertIn(href, self.page)

    def test_legacy_root_hashes_redirect_to_the_workbench(self) -> None:
        self.assertIn('["view", "q", "audit", "kind", "coll", "ci", "sort"]', self.page)
        self.assertIn('location.replace("./workbench/" + location.hash)', self.page)

    def test_landing_avoids_template_and_marketing_antipatterns(self) -> None:
        self.assertNotIn("—", self.page)
        self.assertNotIn("&mdash;", self.page)
        self.assertNotIn("linear-gradient", self.page)
        self.assertNotIn("background-clip", self.page)
        for banned in ("Testimonials", "Pricing", "Logo cloud", "Frequently asked"):
            self.assertNotIn(banned, self.page)
        self.assertNotIn("tailwind-plus", self.page.lower())
        self.assertNotIn("salient", self.page.lower())

    def test_pages_artifact_publishes_both_routes(self) -> None:
        self.assertIn("cp landing.html _site/index.html", self.workflow)
        self.assertIn("cp -R assets _site/assets", self.workflow)
        self.assertIn("cp workbench/index.html _site/workbench/index.html", self.workflow)
        self.assertEqual(
            generate.BOARD_SITE_URL,
            "https://williamjblair.github.io/open-formal-workflows/workbench/",
        )
        self.assertEqual(
            generate.METHOD_URL,
            "https://williamjblair.github.io/open-formal-workflows/workbench/#view=method",
        )


if __name__ == "__main__":
    unittest.main()
