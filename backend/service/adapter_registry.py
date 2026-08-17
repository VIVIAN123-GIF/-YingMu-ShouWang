"""Load algorithm entry points without coupling backend code to model packages."""

from __future__ import annotations

import importlib
import inspect
import os
from collections.abc import Awaitable, Callable
from typing import Any

from contracts.v1.algorithm import AdapterBatch, AlgorithmJob, AlgorithmModule


AdapterCallable = Callable[[AlgorithmJob], AdapterBatch | Awaitable[AdapterBatch]]


class AdapterRegistryError(RuntimeError):
    pass


class AdapterRegistry:
    ENV_BY_MODULE = {
        AlgorithmModule.GAIT: "YINGMU_GAIT_ADAPTER",
        AlgorithmModule.TRAJECTORY: "YINGMU_TRAJECTORY_ADAPTER",
        AlgorithmModule.LANGUAGE: "YINGMU_LANGUAGE_ADAPTER",
    }

    def __init__(self) -> None:
        self._adapters: dict[AlgorithmModule, AdapterCallable] = {}

    def register(self, module: AlgorithmModule, adapter: AdapterCallable) -> None:
        if not callable(adapter):
            raise TypeError("adapter must be callable")
        self._adapters[module] = adapter

    def get(self, module: AlgorithmModule) -> AdapterCallable | None:
        return self._adapters.get(module)

    def load_configured(self) -> None:
        for module, env_name in self.ENV_BY_MODULE.items():
            entrypoint = os.getenv(env_name, "").strip()
            if not entrypoint or module in self._adapters:
                continue
            module_name, separator, attribute = entrypoint.partition(":")
            if not separator or not module_name or not attribute:
                raise AdapterRegistryError(f"{env_name} must use package.module:callable")
            imported = importlib.import_module(module_name)
            adapter = getattr(imported, attribute, None)
            if not callable(adapter):
                raise AdapterRegistryError(f"{env_name} does not resolve to a callable")
            self.register(module, adapter)

    async def invoke(self, module: AlgorithmModule, job: AlgorithmJob) -> AdapterBatch:
        adapter = self.get(module)
        if adapter is None:
            raise AdapterRegistryError(f"ADAPTER_NOT_REGISTERED:{module.value}")
        result: Any = adapter(job)
        if inspect.isawaitable(result):
            result = await result
        return AdapterBatch.model_validate(result)


adapter_registry = AdapterRegistry()
