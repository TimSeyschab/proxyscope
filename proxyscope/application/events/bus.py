from __future__ import annotations

import asyncio
import inspect
import logging
from queue import Full, Queue
from threading import Event as ThreadEvent
from threading import Thread
from typing import Awaitable, Callable

from proxyscope.contracts.events import (
    ArtifactRecorded,
    ComponentDisabled,
    ComponentEnabled,
    ExchangeCompleted,
    MockResponseServed,
    ReplayCompleted,
    ReplayRequested,
    RequestBodyCaptured,
    RequestObserved,
    ResponseBodyCaptured,
    ResponseEditApplied,
    ResponseEditRequested,
    ResponseObserved,
    RuntimeEvent,
    TrafficRuleApplied,
)

LOGGER = logging.getLogger("pscope.events")
EventHandler = Callable[["RuntimeEvent"], object]


class EventBus:
    def __init__(self) -> None:
        self._inline_handlers: list[EventHandler] = []
        self._async_workers: list[_AsyncWorker] = []

    def subscribe(self, handler: EventHandler) -> None:
        self._inline_handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        self._inline_handlers = [registered for registered in self._inline_handlers if registered is not handler]

    def subscribe_async(self, handler: EventHandler, *, max_queue_size: int = 128) -> None:
        self._async_workers.append(_AsyncWorker(handler, max_queue_size=max_queue_size))

    def publish(self, event: RuntimeEvent) -> None:
        for handler in tuple(self._inline_handlers):
            _invoke_handler(handler, event)
        for worker in tuple(self._async_workers):
            worker.submit(event)

    def shutdown(self) -> None:
        for worker in self._async_workers:
            worker.shutdown()
        self._async_workers.clear()


class _AsyncWorker:
    def __init__(self, handler: EventHandler, *, max_queue_size: int) -> None:
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be greater than zero.")
        self._handler = handler
        self._queue: Queue[RuntimeEvent | None] = Queue(maxsize=max_queue_size)
        self._stopped = ThreadEvent()
        self._thread = Thread(target=self._run, name="proxyscope-event-handler", daemon=True)
        self._thread.start()

    def submit(self, event: RuntimeEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except Full:
            LOGGER.warning("Dropping event %s because async handler queue is full.", event.event_type)

    def shutdown(self) -> None:
        self._queue.join()
        self._stopped.set()
        self._queue.put(None)
        self._thread.join()

    def _run(self) -> None:
        while not self._stopped.is_set():
            event = self._queue.get()
            try:
                if event is None:
                    return
                _invoke_handler(self._handler, event)
            finally:
                self._queue.task_done()


def _invoke_handler(handler: EventHandler, event: RuntimeEvent) -> None:
    try:
        result = handler(event)
        if inspect.isawaitable(result):
            asyncio.run(_await_result(result))
    except Exception:  # noqa: BLE001
        LOGGER.exception("Event handler failed for %s.", event.event_type)


async def _await_result(awaitable: Awaitable[object]) -> None:
    await awaitable


__all__ = [
    "ArtifactRecorded",
    "ComponentDisabled",
    "ComponentEnabled",
    "EventBus",
    "ExchangeCompleted",
    "MockResponseServed",
    "ReplayCompleted",
    "ReplayRequested",
    "RequestBodyCaptured",
    "RequestObserved",
    "ResponseBodyCaptured",
    "ResponseEditApplied",
    "ResponseEditRequested",
    "ResponseObserved",
    "RuntimeEvent",
    "TrafficRuleApplied",
]
