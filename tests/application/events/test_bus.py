import threading
import time
import unittest

from proxyscope.application.event_store import EventStoreWriter
from proxyscope.application.events import EventBus, RequestObserved


def _event(*, path: str = "/") -> RequestObserved:
    return RequestObserved(method="GET", path=path, target_host="example.com", target_port=443, protocol="https")


class TestEventModels(unittest.TestCase):
    def test_event_has_stable_required_fields(self) -> None:
        event = _event()
        self.assertTrue(event.event_id)
        self.assertEqual(event.event_type, "request.observed")
        self.assertIsNotNone(event.occurred_at)
        self.assertIsNone(event.request_id)
        self.assertIsNone(event.component_id)


class TestEventBus(unittest.TestCase):
    def test_inline_handlers_run_in_subscription_order(self) -> None:
        bus = EventBus()
        observed: list[str] = []
        bus.subscribe(lambda _event: observed.append("first"))
        bus.subscribe(lambda _event: observed.append("second"))
        bus.publish(_event())
        self.assertEqual(observed, ["first", "second"])

    def test_async_handler_runs_without_blocking_publish(self) -> None:
        bus = EventBus()
        completed = threading.Event()
        bus.subscribe_async(lambda _event: completed.set())
        started_at = time.perf_counter()
        bus.publish(_event())
        self.assertLess(time.perf_counter() - started_at, 0.05)
        self.assertTrue(completed.wait(timeout=1))
        bus.shutdown()

    def test_handler_failure_does_not_stop_other_handlers(self) -> None:
        bus = EventBus()
        observed: list[str] = []

        def broken(_event: RequestObserved) -> None:
            raise RuntimeError("broken")

        bus.subscribe(broken)
        bus.subscribe(lambda _event: observed.append("healthy"))
        bus.publish(_event())
        self.assertEqual(observed, ["healthy"])

    def test_bounded_async_queue_drops_backpressure(self) -> None:
        bus = EventBus()
        started = threading.Event()
        release = threading.Event()
        observed: list[str] = []

        def slow_handler(event: RequestObserved) -> None:
            started.set()
            release.wait(timeout=1)
            observed.append(event.path)

        bus.subscribe_async(slow_handler, max_queue_size=1)
        bus.publish(_event(path="/one"))
        self.assertTrue(started.wait(timeout=1))
        bus.publish(_event(path="/two"))
        bus.publish(_event(path="/three"))
        release.set()
        bus.shutdown()
        self.assertEqual(observed, ["/one", "/two"])

    def test_event_store_writer_drops_events_when_its_queue_is_full(self) -> None:
        class BlockingStore:
            def __init__(self) -> None:
                self.started = threading.Event()
                self.release = threading.Event()
                self.events: list[RequestObserved] = []

            def append(self, event: RequestObserved) -> None:
                self.started.set()
                self.release.wait(timeout=1)
                self.events.append(event)

        store = BlockingStore()
        bus = EventBus()
        bus.subscribe_async(EventStoreWriter(store), max_queue_size=1)
        bus.publish(_event(path="/one"))
        self.assertTrue(store.started.wait(timeout=1))
        bus.publish(_event(path="/two"))
        bus.publish(_event(path="/three"))
        store.release.set()
        bus.shutdown()
        self.assertEqual([event.path for event in store.events], ["/one", "/two"])

    def test_shutdown_drains_async_handlers(self) -> None:
        bus = EventBus()
        observed: list[str] = []
        bus.subscribe_async(lambda event: observed.append(event.path))
        bus.publish(_event(path="/one"))
        bus.publish(_event(path="/two"))
        bus.shutdown()
        self.assertEqual(observed, ["/one", "/two"])


if __name__ == "__main__":
    unittest.main()
