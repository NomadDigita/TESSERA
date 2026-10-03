import os
import unittest
import uuid

from tessera.config import Settings
from tessera.events import RedisStreamBus
from tessera.services import CapitalOrchestrator
from tessera.storage import PostgreSQLStore
from tessera.worker import Worker
from tessera.artifacts import S3ArtifactStore
from tessera.rate_limit import RedisRateLimiter


@unittest.skipUnless(os.getenv("TESSERA_INTEGRATION_TESTS") == "1", "production services not configured")
class ProductionServicesTests(unittest.TestCase):
    def test_postgres_redis_worker_round_trip(self):
        database_url = os.environ["DATABASE_URL"]
        redis_url = os.environ["REDIS_URL"]
        suffix = uuid.uuid4().hex[:8]
        api_bus = RedisStreamBus(redis_url, group=f"integration-{suffix}", consumer="api")
        settings = Settings(database_url=database_url, redis_url=redis_url)
        api = CapitalOrchestrator(PostgreSQLStore(database_url), settings, event_bus=api_bus)
        job = api.enqueue_run({"title": f"Postgres Redis {suffix}", "symbols": ["QQQ"]})

        worker_bus = RedisStreamBus(redis_url, group=f"integration-{suffix}", consumer="worker")
        worker_system = CapitalOrchestrator(PostgreSQLStore(database_url), settings, event_bus=worker_bus)
        message_id = worker_bus.wait("tessera:jobs", 2)
        self.assertIsNotNone(message_id)
        self.assertTrue(Worker(worker_system, f"worker-{suffix}").process_one())
        worker_bus.acknowledge("tessera:jobs", message_id)

        completed = api.store.get_job(job["job_id"])
        self.assertEqual(completed["status"], "succeeded")
        self.assertIn(completed["result"]["run_id"], api.refresh_runs())
        self.assertTrue(api.ledger.verify())
        api.close()
        worker_system.close()

    def test_s3_compatible_artifact_round_trip(self):
        store = S3ArtifactStore(os.environ["OBJECT_STORAGE_ENDPOINT"],
                                os.environ["OBJECT_STORAGE_BUCKET"],
                                os.environ["OBJECT_STORAGE_ACCESS_KEY"],
                                os.environ["OBJECT_STORAGE_SECRET_KEY"])
        store.ensure_bucket()
        payload = {"schema": "integration", "value": uuid.uuid4().hex}
        reference = store.put_json(f"integration/{uuid.uuid4().hex}.json", payload)
        self.assertEqual(store.get_json(reference["key"]), payload)
        self.assertEqual(len(reference["sha256"]), 64)

    def test_redis_rate_limit_is_shared(self):
        key = f"integration:{uuid.uuid4().hex}"
        first = RedisRateLimiter(os.environ["REDIS_URL"])
        second = RedisRateLimiter(os.environ["REDIS_URL"])
        self.assertTrue(first.consume(key, 1, 60).allowed)
        denied = second.consume(key, 1, 60)
        self.assertFalse(denied.allowed)
        self.assertGreater(denied.retry_after, 0)


if __name__ == "__main__":
    unittest.main()
