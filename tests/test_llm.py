import unittest

from tessera.llm import DeterministicProvider, LLMError, LLMRouter


class FailingProvider:
    name = "failing"
    model = "fixture"

    def complete_json(self, system_prompt, payload):
        raise LLMError("fixture failure")


class LLMTests(unittest.TestCase):
    def test_fallback_provider_is_audited_and_used(self):
        calls = []
        result = LLMRouter([FailingProvider(), DeterministicProvider()], calls.append).structured_call(
            "market_intelligence", "return JSON", {"title": "test", "severity": 0.7, "symbols": ["NVDA"]}, "run-1")
        self.assertEqual(result["decision"], "EVENT_CONFIRMED")
        self.assertEqual([call["provider"] for call in calls], ["failing", "deterministic"])
        self.assertEqual(calls[-1]["validation_status"], "valid")


if __name__ == "__main__":
    unittest.main()
