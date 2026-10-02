import tempfile
import unittest
from pathlib import Path

from tessera.artifacts import LocalArtifactStore
from tessera.config import Settings
from tessera.services import CapitalOrchestrator
from tessera.storage import SQLiteStore


class ArtifactTests(unittest.TestCase):
    def test_local_store_blocks_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalArtifactStore(directory)
            with self.assertRaises(ValueError):
                store.put_json("../escape.json", {"unsafe": True})

    def test_replay_bundle_is_durable_and_integrity_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(database_path=":memory:", artifact_path=directory)
            system = CapitalOrchestrator(SQLiteStore(":memory:"), settings)
            original = system.create_run({"title": "Pinned replay", "symbols": ["QQQ"]})
            replay_run = system.replay(original.run_id)
            record = system.store.list_replays()[0]
            bundle = system.replay_bundle(record["replay_id"])
            self.assertEqual(bundle["original_run"]["run_id"], original.run_id)
            self.assertEqual(bundle["replay_run"]["run_id"], replay_run.run_id)
            self.assertEqual(bundle["constitution_version"], system.risk.version)
            self.assertTrue(bundle["ledger_entries"])

            artifact = Path(directory) / record["artifact"]["key"]
            artifact.write_text('{"tampered":true}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "integrity"):
                system.replay_bundle(record["replay_id"])


if __name__ == "__main__":
    unittest.main()
