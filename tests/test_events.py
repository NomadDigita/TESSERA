import unittest

from tessera.events import MemoryEventBus


class EventBusTests(unittest.TestCase):
    def test_memory_stream_wakes_consumer(self):
        bus = MemoryEventBus()
        published = bus.publish("tessera:jobs", {"job_id": "one"})
        received = bus.wait("tessera:jobs", 0.01)
        self.assertEqual(received, published)
        bus.acknowledge("tessera:jobs", received)
        self.assertIsNone(bus.wait("tessera:jobs", 0.01))


if __name__ == "__main__":
    unittest.main()
