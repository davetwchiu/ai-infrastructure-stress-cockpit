import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_hermes import promote, validate_candidate

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class HermesValidatorTests(unittest.TestCase):
    def setUp(self):
        self.market = json.loads((ROOT / "data" / "latest.json").read_text())

    def fixture(self, name):
        return json.loads((FIXTURES / name).read_text())

    def test_august_fixture_warns_but_publishes_and_synthesizes(self):
        result = validate_candidate(self.fixture("hermes_candidate_aug10_2026.json"), self.market)
        self.assertEqual(result["validation"]["status"], "pass_with_warnings")
        codes = {item["code"] for item in result["validation"]["warnings"]}
        self.assertTrue({"low_quality_source_dependency", "unsupported_cross_entity_inference", "ambiguous_unit_period"} <= codes)
        credit = next(item for item in result["theses"] if item["id"] == "credit-stress")
        self.assertEqual(credit["validated_confidence"], .78)
        self.assertEqual(result["market_research_synthesis"]["state"], "RESEARCH_LEADS")

    def test_tier_four_confirmed_is_rejected(self):
        result = validate_candidate(self.fixture("hermes_candidate_invalid_confirmed_tier4.json"), self.market)
        self.assertEqual(result["validation"]["status"], "fail")
        self.assertIn("confirmed_promotion_gate", {item["code"] for item in result["validation"]["errors"]})

    def test_incomparable_capex_aggregate_is_rejected_and_prior_state_is_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            candidate = base / "candidate.json"
            candidate.write_text(json.dumps(self.fixture("hermes_candidate_invalid_capex_aggregation.json")))
            output = base / "latest.json"
            output.write_text(json.dumps({"run": {"run_id": "previous"}, "validation": {"validated_at": "2026-08-01T00:00:00+00:00"}}))
            result = promote(candidate, ROOT / "data" / "latest.json", output, base / "history.jsonl", base / "validation.json")
            self.assertEqual(result["validation"]["status"], "fail")
            self.assertEqual(json.loads(output.read_text())["run"]["run_id"], "previous")

    def test_change_detection_is_authoritative(self):
        first = validate_candidate(self.fixture("hermes_candidate_aug10_2026.json"), self.market)
        changed = self.fixture("hermes_candidate_aug10_2026.json")
        changed["run"]["run_id"] = "hermes-2026-08-10-b"
        changed["theses"][5]["status"] = "confirmed"
        changed["theses"][5]["raw_confidence"] = .95
        result = validate_candidate(changed, self.market, first)
        self.assertEqual(result["validation"]["status"], "pass_with_warnings")
        self.assertIn("status_change", {item["type"] for item in result["changes"]})


if __name__ == "__main__":
    unittest.main()
