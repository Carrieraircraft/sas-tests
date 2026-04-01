"""WebSocket 测试客户端 —— 封装连接、收发、请求-响应匹配与事件分发"""

import asyncio
import json
import logging
import time
from typing import Callable, Optional, Sequence

import websockets
from websockets.protocol import OPEN

from .constants import MsgType, DEFAULT_WS_TIMEOUT
from .event_accumulator import EventAccumulator

logger = logging.getLogger(__name__)

_IGNORED_TYPES = frozenset({MsgType.PING, MsgType.PONG})


class WSClient:

    def __init__(self):
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._events = EventAccumulator()
        self._pending_responses: dict[str, asyncio.Queue] = {}
        self._last_elapsed_ms: float = 0.0

    # ── 连接管理 ─────────────────────────────────────────────────

    async def connect(self, url: str) -> None:
        self._ws = await websockets.connect(url)
        self._recv_task = asyncio.create_task(self._recv_loop())
        logger.info("Connected to %s", url)

    async def disconnect(self) -> None:
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        logger.info("Disconnected")

    # ── 发送 ─────────────────────────────────────────────────────

    async def send(self, message: dict) -> None:
        assert self._ws is not None, "Not connected"
        await self._ws.send(json.dumps(message, ensure_ascii=False))

    async def send_raw(self, text: str) -> None:
        assert self._ws is not None, "Not connected"
        await self._ws.send(text)

    # ── 接收 ─────────────────────────────────────────────────────

    async def recv(self, timeout: float = DEFAULT_WS_TIMEOUT) -> dict:
        """接收一条消息并自动 JSON 解析，超时抛出 TimeoutError。"""
        assert self._ws is not None, "Not connected"
        raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
        return json.loads(raw)

    # ── 请求-响应 ────────────────────────────────────────────────

    async def request(
        self,
        message: dict,
        response_type: str,
        timeout: float = DEFAULT_WS_TIMEOUT,
    ) -> dict:
        queue = self._ensure_queue(response_type)
        t0 = time.monotonic()
        await self.send(message)
        try:
            resp = await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"No '{response_type}' response within {timeout:.1f}s"
            )
        self._last_elapsed_ms = (time.monotonic() - t0) * 1000
        return resp

    async def request_any(
        self,
        message: dict,
        response_types: Sequence[str],
        timeout: float = DEFAULT_WS_TIMEOUT,
    ) -> dict:
        """发送并等待任一指定类型的首条响应（用于成功/错误分支不同 type 的接口）。"""
        queues = [self._ensure_queue(t) for t in response_types]
        t0 = time.monotonic()
        await self.send(message)
        get_tasks = [
            asyncio.create_task(q.get()) for q in queues
        ]
        done, pending = await asyncio.wait(
            get_tasks,
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        if not done:
            raise TimeoutError(
                f"No response in {response_types!r} within {timeout:.1f}s"
            )
        resp = next(iter(done)).result()
        self._last_elapsed_ms = (time.monotonic() - t0) * 1000
        return resp

    async def wait_for(
        self, msg_type: str, timeout: float = DEFAULT_WS_TIMEOUT
    ) -> dict:
        queue = self._ensure_queue(msg_type)
        try:
            return await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"No '{msg_type}' message within {timeout:.1f}s"
            )

    async def wait_for_condition(
        self,
        predicate: Callable[[dict], bool],
        timeout: float = DEFAULT_WS_TIMEOUT,
    ) -> dict:
        """轮询事件累积器，等待满足 predicate 的消息。"""
        deadline = time.monotonic() + timeout
        while True:
            all_events = await self._events.get_all()
            for ev in all_events:
                if predicate(ev):
                    return ev
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Condition not met within {timeout:.1f}s"
                )
            await asyncio.sleep(min(0.05, remaining))

    # ── 属性 ─────────────────────────────────────────────────────

    @property
    def last_elapsed_ms(self) -> float:
        return self._last_elapsed_ms

    @property
    def connected(self) -> bool:
        """兼容旧版 `WebSocketClientProtocol.open` 与新版 `ClientConnection.state`。"""
        if self._ws is None:
            return False
        ws = self._ws
        if hasattr(ws, "open"):
            return bool(ws.open)
        st = getattr(ws, "state", None)
        if st is not None:
            return st is OPEN
        return not getattr(ws, "closed", False)

    @property
    def events(self) -> EventAccumulator:
        return self._events

    # ── 便捷方法 ─────────────────────────────────────────────────

    async def get_spec_list(self) -> list:
        resp = await self.request(
            {"type": MsgType.SPEC_OPTIONS_GET},
            MsgType.SPEC_OPTIONS_RESPONSE,
        )
        return resp.get("data", [])

    async def get_module_list(self) -> list:
        resp = await self.request(
            {"type": MsgType.MODULE_LIST_GET},
            MsgType.MODULE_LIST_RESPONSE,
        )
        return resp.get("data", [])

    async def get_module(self, module_id: int) -> dict:
        return await self.request_any(
            {"type": MsgType.MODULE_GET, "module_id": module_id},
            (MsgType.MODULE_GET_RESPONSE, MsgType.MODULE_ERROR),
        )

    async def get_screw_steps(self, spec_id: int) -> dict:
        return await self.request(
            {"type": MsgType.SCREW_STEP_GET, "specification_id": spec_id},
            MsgType.SCREW_STEP_RESPONSE,
        )

    async def burst_same_response(
        self,
        messages: list[dict],
        response_type: str,
        timeout_each: float = DEFAULT_WS_TIMEOUT,
    ) -> list[dict]:
        """连续发送多条请求，再按顺序读取同类型响应（用于积压/顺序测试）。"""
        q = self._ensure_queue(response_type)
        for m in messages:
            await self.send(m)
        out: list[dict] = []
        t0 = time.monotonic()
        for _ in messages:
            out.append(await asyncio.wait_for(q.get(), timeout=timeout_each))
        self._last_elapsed_ms = (time.monotonic() - t0) * 1000
        return out

    async def get_system_params(self) -> dict:
        await self.send_raw("data:request:system_params")
        return await self.wait_for_condition(
            lambda m: (
                m.get("type") == MsgType.DATA_RESPONSE
                and m.get("data_type") == "system_params"
            ),
        )

    async def save_screw_param(self, spec_id: int, data: dict) -> dict:
        msg = dict(data)
        msg.setdefault("type", MsgType.SCREW_PARAM_CONFIG)
        msg.setdefault("specification_id", spec_id)
        return await self.request(msg, MsgType.SCREW_PARAM_SAVE_RESPONSE)

    async def get_screw_param(self, spec_id: int) -> dict:
        return await self.request(
            {"type": MsgType.SCREW_PARAM_GET, "specification_id": spec_id},
            MsgType.SCREW_PARAM_GET_RESPONSE,
        )

    async def query_screw_reference(self, screw_id: int) -> dict:
        return await self.request(
            {"type": MsgType.SPEC_REF_QUERY, "screw_id": screw_id},
            MsgType.SPEC_REF_RESPONSE,
        )

    async def clone_screw_spec(self, source_id: int, target_id: int) -> dict:
        return await self.request(
            {
                "type": MsgType.SPEC_CLONE,
                "source_id": source_id,
                "target_id": target_id,
            },
            MsgType.SPEC_CLONE_RESPONSE,
        )

    async def save_module(self, module_id: int, data: dict) -> dict:
        msg = dict(data)
        msg.setdefault("type", MsgType.MODULE_CONFIG)
        msg.setdefault("module_id", module_id)
        return await self.request_any(
            msg,
            (MsgType.MODULE_CONFIG_RESPONSE, MsgType.MODULE_ERROR),
        )

    # ── 内部 ─────────────────────────────────────────────────────

    def _ensure_queue(self, msg_type: str) -> asyncio.Queue:
        if msg_type not in self._pending_responses:
            self._pending_responses[msg_type] = asyncio.Queue()
        return self._pending_responses[msg_type]

    async def _recv_loop(self) -> None:
        """后台持续接收并分发消息。连接关闭或任务取消时退出。"""
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Non-JSON message ignored: %s", raw[:200])
                    continue

                msg_type = msg.get("type")

                if msg_type in _IGNORED_TYPES:
                    continue

                if msg_type and msg_type in self._pending_responses:
                    await self._pending_responses[msg_type].put(msg)
                else:
                    await self._events.push(msg)
        except websockets.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except asyncio.CancelledError:
            raise
