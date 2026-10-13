import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from portfoliolens.copilot import ask, openai_generate

ROOT = Path(__file__).resolve().parents[1]


class CopilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((ROOT / "artifacts/dashboard.json").read_text())
        cls.evidence = [cls.report["evidence"][0]]

    def good_answer(self):
        return {"summary":"Inspect the computed evidence before interpreting the portfolio movement.",
                "evidence_ids":[self.evidence[0]["id"]], "recommended_checks":["Review source reconciliation."],
                "limitations":["Synthetic data only."]}

    def transport(self, answer, status="completed"):
        return lambda request: {"status":status, "output":[{"type":"message", "content":[
            {"type":"output_text", "text":json.dumps(answer)}]}]}

    def test_development_set_expected_sources_and_behavior(self):
        for case in json.loads((ROOT / "docs/eval_cases.json").read_text()):
            with self.subTest(question=case["question"]):
                result = ask(self.report, case["question"])
                self.assertEqual(result["intent"], case["intent"])
                self.assertEqual(result["status"], "abstained" if case["intent"] == "unsupported" else "answered")
                if case["source"]:
                    self.assertIn(case["source"], result["evidence_ids"])

    def test_causality_is_not_claimed(self):
        result = ask(self.report, "What caused the delinquency change?")
        self.assertIn("does not establish causation", result["summary"])
        self.assertIn("D-CAUSE", result["evidence_ids"])

    def test_unsupported_inputs(self):
        for query in ["", "x"*1001, None]:
            with self.assertRaises(ValueError):
                ask(self.report, query)
        with self.assertRaises(ValueError):
            ask(self.report, "Portfolio", "bad-mode")

    @patch.dict(os.environ, {"OPENAI_API_KEY":"unit-test-only", "OPENAI_MODEL":"unit-test-model"})
    def test_openai_request_contract_and_valid_output(self):
        def transport(request):
            payload = json.loads(request.data)
            self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
            self.assertFalse(payload["store"])
            self.assertTrue(payload["text"]["format"]["strict"])
            self.assertEqual(payload["text"]["format"]["type"], "json_schema")
            self.assertNotIn("unit-test-only", payload["input"])
            return self.transport(self.good_answer())(request)
        result = openai_generate("Portfolio", self.evidence, transport)
        self.assertEqual(result["evidence_ids"], [self.evidence[0]["id"]])

    @patch.dict(os.environ, {"OPENAI_API_KEY":"unit-test-only", "OPENAI_MODEL":"unit-test-model"})
    def test_unverified_citation_is_rejected(self):
        answer = self.good_answer()
        answer["evidence_ids"] = ["MADE-UP"]
        with self.assertRaisesRegex(ValueError, "unsupported evidence"):
            openai_generate("Portfolio", self.evidence, self.transport(answer))

    @patch.dict(os.environ, {"OPENAI_API_KEY":"unit-test-only", "OPENAI_MODEL":"unit-test-model"})
    def test_llm_numeric_assertion_is_rejected(self):
        answer = self.good_answer()
        answer["summary"] = "Delinquency is 99.9%."
        with self.assertRaisesRegex(ValueError, "Numeric"):
            openai_generate("Portfolio", self.evidence, self.transport(answer))

    @patch.dict(os.environ, {"OPENAI_API_KEY":"unit-test-only", "OPENAI_MODEL":"unit-test-model"})
    def test_incomplete_response_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            openai_generate("Portfolio", self.evidence, self.transport(self.good_answer(), "incomplete"))

    @patch.dict(os.environ, {"OPENAI_API_KEY":"unit-test-only", "OPENAI_MODEL":"unit-test-model"})
    def test_refusal_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "declined"):
            openai_generate("Portfolio", self.evidence, lambda request: {"status":"completed", "output":[
                {"content":[{"type":"refusal", "refusal":"No"}]}]})

    @patch.dict(os.environ, {"OPENAI_API_KEY":"", "OPENAI_MODEL":""})
    def test_missing_credentials_are_clear(self):
        with self.assertRaisesRegex(ValueError, "needs OPENAI"):
            openai_generate("Portfolio", self.evidence)


if __name__ == "__main__":
    unittest.main()
