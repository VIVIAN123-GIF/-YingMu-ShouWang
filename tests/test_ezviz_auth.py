from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from backend.utils import ezviz_auth as auth_module
from backend.utils.ezviz_auth import EzvizAuth, EzvizTokenInvalidError


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def json(self) -> dict:
        return self.payload


class FakeAsyncClient:
    def __init__(self, responder: Callable[[str], dict], calls: list[str], **_kwargs):
        self.responder = responder
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url: str, **_kwargs):
        self.calls.append(url.rsplit("/", 1)[-1])
        return FakeResponse(self.responder(url))

    async def get(self, url: str, **_kwargs):
        self.calls.append(url.rsplit("/", 1)[-1])
        return FakeResponse(self.responder(url))


def install_transport(monkeypatch, payloads: list[dict]) -> list[str]:
    calls: list[str] = []

    def responder(_url: str) -> dict:
        return payloads.pop(0)

    monkeypatch.setattr(
        auth_module.httpx,
        "AsyncClient",
        lambda **kwargs: FakeAsyncClient(responder, calls, **kwargs),
    )
    return calls


def test_invalid_token_refreshes_once_then_succeeds(monkeypatch):
    calls = install_transport(monkeypatch, [
        {"code": "10002", "msg": "invalid"},
        {"code": "200", "data": {"status": 1}},
    ])
    token_calls = 0
    sleep_calls = 0

    async def get_token() -> str:
        nonlocal token_calls
        token_calls += 1
        return f"mock-token-{token_calls}"

    async def no_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1

    monkeypatch.setattr(EzvizAuth, "get_valid_token", get_token)
    monkeypatch.setattr(auth_module.asyncio, "sleep", no_sleep)
    auth_module._TOKEN_STORE = {"token": "mock-cached", "expire_time": 9999999999}
    auth_module._ENV_TOKEN_REJECTED = False

    result = asyncio.run(EzvizAuth.request("/device/info", body={"deviceSerial": "mock-device"}))

    assert result["code"] == "200"
    assert token_calls == 2
    assert len(calls) == 2
    assert sleep_calls == 0
    assert auth_module._TOKEN_STORE is None
    assert auth_module._ENV_TOKEN_REJECTED is True


def test_invalid_token_after_refresh_stops_immediately(monkeypatch):
    calls = install_transport(monkeypatch, [
        {"code": "10002", "msg": "invalid"},
        {"code": "10018", "msg": "expired"},
    ])
    token_calls = 0
    sleep_calls = 0

    async def get_token() -> str:
        nonlocal token_calls
        token_calls += 1
        return f"mock-token-{token_calls}"

    async def no_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1

    monkeypatch.setattr(EzvizAuth, "get_valid_token", get_token)
    monkeypatch.setattr(auth_module.asyncio, "sleep", no_sleep)
    auth_module._TOKEN_STORE = {"token": "mock-cached", "expire_time": 9999999999}
    auth_module._ENV_TOKEN_REJECTED = False

    with pytest.raises(EzvizTokenInvalidError) as exc_info:
        asyncio.run(EzvizAuth.request("/device/info", body={"deviceSerial": "mock-device"}))

    assert exc_info.value.error_code == "EZVIZ_TOKEN_INVALID_AFTER_REFRESH"
    assert exc_info.value.provider_code == "10018"
    assert token_calls == 2
    assert len(calls) == 2
    assert sleep_calls == 0


def test_offline_device_response_is_not_retried(monkeypatch):
    calls = install_transport(monkeypatch, [
        {"code": "200", "data": {"status": 0}},
    ])
    token_calls = 0

    async def get_token() -> str:
        nonlocal token_calls
        token_calls += 1
        return "mock-token"

    monkeypatch.setattr(EzvizAuth, "get_valid_token", get_token)

    result = asyncio.run(EzvizAuth.request("/device/info", body={"deviceSerial": "mock-device"}))

    assert result == {"code": "200", "data": {"status": 0}}
    assert token_calls == 1
    assert calls == ["info"]
