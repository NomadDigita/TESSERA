from __future__ import annotations

import os
import signal
import socket
import time

from .config import Settings
from .observability import LOGGER, METRICS
from .services import CapitalOrchestrator
from .storage import create_store
from .events import create_event_bus


class Worker:
    def __init__(self, orchestrator: CapitalOrchestrator, worker_id: str | None = None) -> None:
        self.orchestrator = orchestrator
        self.store = orchestrator.store
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self.event_bus = orchestrator.event_bus
        self.running = True

    def stop(self, *_args) -> None:
        self.running = False

    def process_one(self) -> bool:
        job = self.store.claim_job(self.worker_id)
        if not job:
            return False
        started = time.perf_counter()
        try:
            if job["job_type"] != "create_run":
                raise ValueError(f"Unsupported job type: {job['job_type']}")
            run = self.orchestrator.create_run(job["payload"], idempotency_key=f"job:{job['job_id']}")
            result = {"run_id": run.run_id, "status": run.status}
            self.store.finish_job(job["job_id"], result)
            METRICS.inc("worker_jobs_total", labels={"status": "succeeded", "type": job["job_type"]})
            LOGGER.info("job_succeeded", extra={"context": {"job_id": job["job_id"], "worker_id": self.worker_id,
                                                               "duration_ms": round((time.perf_counter() - started) * 1000, 2)}})
        except Exception as exc:
            self.store.fail_job(job["job_id"], f"{type(exc).__name__}: {exc}")
            METRICS.inc("worker_jobs_total", labels={"status": "failed", "type": job["job_type"]})
            LOGGER.exception("job_failed", extra={"context": {"job_id": job["job_id"], "worker_id": self.worker_id}})
        return True

    def run(self, poll_seconds: float = 1.0) -> None:
        LOGGER.info("worker_start", extra={"context": {"worker_id": self.worker_id}})
        while self.running:
            message_id = self.event_bus.wait("tessera:jobs", poll_seconds)
            processed = self.process_one()
            if message_id:
                self.event_bus.acknowledge("tessera:jobs", message_id)
        LOGGER.info("worker_stop", extra={"context": {"worker_id": self.worker_id}})


def main() -> None:
    settings = Settings.from_env()
    settings.prepare_runtime()
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    store = create_store(settings.database_url, settings.database_path)
    event_bus = create_event_bus(settings.redis_url, worker_id)
    orchestrator = CapitalOrchestrator(store, settings, event_bus=event_bus)
    worker = Worker(orchestrator, worker_id)
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    try:
        worker.run(float(os.getenv("TESSERA_WORKER_POLL_SECONDS", "1")))
    finally:
        orchestrator.close()


if __name__ == "__main__":
    main()
