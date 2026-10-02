import json
import logging
import unittest

from tessera.observability import JsonFormatter, Metrics
from tessera.services import CapitalOrchestrator


class ObservabilityTests(unittest.TestCase):
    def test_json_logs_redact_sensitive_context(self):
        record = logging.LogRecord("tessera", logging.INFO, "", 0, "provider_call", (), None)
        record.context = {"request_id": "r-1", "api_key": "secret-value", "nested": {"password": "hidden"},
                          "object_storage_secret_key": "also-hidden"}
        payload = json.loads(JsonFormatter().format(record))
        self.assertEqual(payload["api_key"], "[REDACTED]")
        self.assertEqual(payload["nested"]["password"], "[REDACTED]")
        self.assertNotIn("secret-value", json.dumps(payload))
        self.assertEqual(payload["object_storage_secret_key"], "[REDACTED]")

    def test_metrics_render_prometheus_labels(self):
        metrics = Metrics()
        metrics.inc("requests_total", labels={"status": "200"})
        metrics.gauge("runs", 3)
        rendered = metrics.render()
        self.assertIn('tessera_requests_total{status="200"} 1', rendered)
        self.assertIn("tessera_runs 3", rendered)

    def test_readiness_detects_ledger_tampering(self):
        system = CapitalOrchestrator()
        system.create_run({"title": "Readiness"})
        ready, _ = system.readiness()
        self.assertTrue(ready)
        with system.store._db:
            system.store._db.execute(
                "UPDATE ledger_entries SET payload=? WHERE sequence=1",
                ('{"title":"tampered"}',),
            )
        ready, result = system.readiness()
        self.assertFalse(ready)
        self.assertFalse(result["checks"]["ledger"])


if __name__ == "__main__":
    unittest.main()
