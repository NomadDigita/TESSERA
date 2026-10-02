import unittest
import tempfile
from pathlib import Path
from tessera.domain import CausalLedger
from tessera.services import CapitalOrchestrator, RiskConstitution
from tessera.storage import SQLiteStore


class TesseraTests(unittest.TestCase):
    def test_vertical_slice_requires_approval_then_fills(self):
        system = CapitalOrchestrator()
        run = system.create_run({"title": "Test event", "severity": 0.8})
        self.assertEqual(run.status, "AWAITING_APPROVAL")
        system.approve(run.run_id)
        self.assertEqual(system.runs[run.run_id].status, "EXECUTED")
        self.assertEqual(len(system.broker.positions), 1)
        self.assertTrue(system.ledger.verify())

    def test_risk_constitution_vetoes_large_order(self):
        risk = RiskConstitution().evaluate({"proposed_orders": [{"symbol": "NVDA", "quantity": 20, "reference_price": 150}]}, {}, {})
        self.assertEqual(risk["decision"], "deny")
        self.assertTrue(any(v["rule"] == "MAX_ORDER_NOTIONAL" for v in risk["violations"]))

    def test_ledger_detects_tampering(self):
        ledger = CausalLedger()
        ledger.append("r", "event", "test", {"value": 1})
        self.assertTrue(ledger.verify())
        ledger.entries[0].payload["value"] = 2
        self.assertFalse(ledger.verify())

    def test_replay_is_new_run_with_same_event(self):
        system = CapitalOrchestrator()
        original = system.create_run({"title": "Replay me", "severity": 0.7})
        replay = system.replay(original.run_id)
        self.assertNotEqual(original.run_id, replay.run_id)
        self.assertEqual(original.event, replay.event)
        self.assertEqual(replay.replay_of, original.run_id)

    def test_state_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "tessera.db")
            first = CapitalOrchestrator(SQLiteStore(path))
            run = first.create_run({"title": "Persistent event", "severity": 0.8})
            first.approve(run.run_id)
            second = CapitalOrchestrator(SQLiteStore(path))
            self.assertEqual(second.runs[run.run_id].status, "EXECUTED")
            self.assertEqual(second.broker.positions["NVDA"]["quantity"], 5.0)
            self.assertTrue(second.ledger.verify())
            first.close()
            second.close()

    def test_invalid_live_trading_configuration_is_rejected(self):
        from tessera.config import Settings
        with self.assertRaises(ValueError):
            Settings(live_trading_enabled=True).validate()


if __name__ == "__main__":
    unittest.main()
