import asyncio

from backend.service.algorithm_gateway import AlgorithmGateway


def test_retries_transient_failure_then_succeeds():
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("temporary network error")
        return {"score": 0.9}

    result = asyncio.run(
        AlgorithmGateway(max_retries=1, backoff_seconds=(0,)).run("gait", operation)
    )

    assert result.ok is True
    assert result.degraded is False
    assert result.attempts == 2
    assert result.output == {"score": 0.9}


def test_parallel_modules_are_isolated_and_failed_module_degrades():
    def broken():
        raise ValueError("invalid audio frame")

    async def healthy():
        return {"risk": "low"}

    results = asyncio.run(
        AlgorithmGateway(max_retries=0).run_many(
            {"voice": broken, "behavior": healthy},
            fallbacks={"voice": {"status": "audio_quality_low"}},
        )
    )

    assert results["voice"].ok is False
    assert results["voice"].degraded is True
    assert results["voice"].output == {"status": "audio_quality_low"}
    assert results["behavior"].ok is True
    assert results["behavior"].output == {"risk": "low"}


def test_circuit_opens_after_failure_and_stops_repeated_calls():
    calls = 0

    def unavailable():
        nonlocal calls
        calls += 1
        raise ConnectionError("unavailable")

    gateway = AlgorithmGateway(
        max_retries=0, failure_threshold=1, recovery_seconds=60,
    )
    first = asyncio.run(gateway.run("pose", unavailable, fallback={"status": "unavailable"}))
    second = asyncio.run(gateway.run("pose", unavailable, fallback={"status": "unavailable"}))

    assert first.error == "unavailable"
    assert second.error == "circuit_open"
    assert second.attempts == 0
    assert calls == 1

