"""异步事件收集器 —— 后台收集后端主动推送的非请求响应消息"""

import asyncio
import time
from typing import Callable, Optional


class EventAccumulator:

    def __init__(self):
        self._events: list[dict] = []
        self._lock = asyncio.Lock()
        self._new_event = asyncio.Event()

    async def push(self, message: dict) -> None:
        message["_received_at"] = time.monotonic()
        async with self._lock:
            self._events.append(message)
        self._new_event.set()

    async def clear(self) -> None:
        async with self._lock:
            self._events.clear()
        self._new_event.clear()

    async def get_all(self, type_filter: Optional[str] = None) -> list[dict]:
        async with self._lock:
            if type_filter is None:
                return list(self._events)
            return [e for e in self._events if e.get("type") == type_filter]

    async def wait_for_event(
        self,
        event_type: str,
        timeout: float = 5.0,
        predicate: Optional[Callable[[dict], bool]] = None,
    ) -> dict:
        """等待特定类型的事件出现，可附加自定义断言条件。超时抛出 TimeoutError。"""
        deadline = time.monotonic() + timeout
        while True:
            async with self._lock:
                for ev in self._events:
                    if ev.get("type") != event_type:
                        continue
                    if predicate is None or predicate(ev):
                        return ev

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Timed out waiting for event '{event_type}' "
                    f"after {timeout:.1f}s"
                )

            self._new_event.clear()
            try:
                await asyncio.wait_for(self._new_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Timed out waiting for event '{event_type}' "
                    f"after {timeout:.1f}s"
                )

    async def assert_event_occurred(self, event_type: str) -> dict:
        async with self._lock:
            for ev in self._events:
                if ev.get("type") == event_type:
                    return ev
        raise AssertionError(f"Expected event '{event_type}' was never received")

    async def assert_no_event(self, event_type: str) -> None:
        async with self._lock:
            for ev in self._events:
                if ev.get("type") == event_type:
                    raise AssertionError(
                        f"Event '{event_type}' should not have occurred, "
                        f"but was received at {ev.get('_received_at')}"
                    )

    @property
    def count(self) -> int:
        return len(self._events)
