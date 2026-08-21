"""统一的算法调用容错层。

算法模块仍然拥有特征提取和 Observation/Evidence 适配；本模块只负责调用边界的
超时、有限重试、熔断和降级，避免某一个算法故障拖垮整条链路。
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable


@dataclass(frozen=True)
class AlgorithmResult:
    module: str
    ok: bool
    degraded: bool
    attempts: int
    elapsed_ms: int
    output: Any = None
    error: str | None = None


@dataclass
class _Circuit:
    failures: int = 0
    opened_at: float | None = None


class AlgorithmGateway:
    """调用一个或多个算法模块，并把故障转换为可审计的结果。

    ``operation`` 可以是同步函数，也可以是无参异步函数。重试只针对超时、连接
    和操作系统级临时错误；业务校验错误不会被无意义地重复调用。
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        max_retries: int = 2,
        backoff_seconds: Iterable[float] = (0.2, 0.5),
        failure_threshold: int = 3,
        recovery_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0 or max_retries < 0:
            raise ValueError("timeout_seconds must be positive and max_retries non-negative")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = tuple(backoff_seconds)
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_seconds = max(0.0, recovery_seconds)
        self._circuits: dict[str, _Circuit] = {}

    def _circuit_open(self, module: str, now: float) -> bool:
        state = self._circuits.setdefault(module, _Circuit())
        if state.opened_at is None:
            return False
        if now - state.opened_at >= self.recovery_seconds:
            # Half-open: allow one probe request.
            state.opened_at = None
            return False
        return True

    def _record_success(self, module: str) -> None:
        self._circuits[module] = _Circuit()

    def _record_failure(self, module: str) -> None:
        state = self._circuits.setdefault(module, _Circuit())
        state.failures += 1
        if state.failures >= self.failure_threshold:
            state.opened_at = time.monotonic()

    async def run(
        self,
        module: str,
        operation: Callable[[], Any] | Callable[[], Awaitable[Any]],
        *,
        fallback: Callable[[Exception | None], Any] | Any = None,
    ) -> AlgorithmResult:
        started = time.monotonic()
        if self._circuit_open(module, started):
            value = fallback(None) if callable(fallback) else fallback
            return AlgorithmResult(module, False, True, 0, self._elapsed(started), value, "circuit_open")

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            try:
                if inspect.iscoroutinefunction(operation):
                    value = await asyncio.wait_for(operation(), timeout=self.timeout_seconds)
                else:
                    # 同步算法在工作线程中运行，不能阻塞 FastAPI 事件循环。
                    value = await asyncio.wait_for(asyncio.to_thread(operation), timeout=self.timeout_seconds)
                    if inspect.isawaitable(value):
                        value = await asyncio.wait_for(value, timeout=self.timeout_seconds)
                self._record_success(module)
                return AlgorithmResult(module, True, False, attempt, self._elapsed(started), value)
            except asyncio.TimeoutError as exc:
                last_error = TimeoutError(f"{module} timed out after {self.timeout_seconds}s")
                last_error.__cause__ = exc
            except (ConnectionError, OSError) as exc:
                last_error = exc
            except Exception as exc:  # isolate an individual module from the pipeline
                last_error = exc

            if attempt <= self.max_retries and isinstance(last_error, (TimeoutError, ConnectionError, OSError)):
                delay = self.backoff_seconds[min(attempt - 1, len(self.backoff_seconds) - 1)] if self.backoff_seconds else 0
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            break

        self._record_failure(module)
        value = fallback(last_error) if callable(fallback) else fallback
        return AlgorithmResult(module, False, True, attempt, self._elapsed(started), value, str(last_error))

    async def run_many(
        self,
        operations: dict[str, Callable[[], Any] | Callable[[], Awaitable[Any]]],
        *,
        fallbacks: dict[str, Callable[[Exception | None], Any] | Any] | None = None,
    ) -> dict[str, AlgorithmResult]:
        """并行执行并隔离结果；一个模块失败不会取消其他模块。"""
        fallbacks = fallbacks or {}
        names = list(operations)
        results = await asyncio.gather(
            *(self.run(name, operations[name], fallback=fallbacks.get(name)) for name in names),
            return_exceptions=False,
        )
        return dict(zip(names, results))

    @staticmethod
    def _elapsed(started: float) -> int:
        return round((time.monotonic() - started) * 1000)
