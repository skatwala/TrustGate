import asyncio
import logging
import time
from trustgate.decorators import set_trace_id, get_trace_id, log_call, retry


def test_trace_basic():
    set_trace_id(None)
    assert get_trace_id() is None
    set_trace_id("t1")
    assert get_trace_id() == "t1"
    set_trace_id(None)
    assert get_trace_id() is None


def test_log_call_logs_and_redacts(caplog):
    set_trace_id("trace-xyz")

    @log_call(include_args=True, include_result=True)
    def foo(token: str) -> str:
        return "ok"

    with caplog.at_level(logging.INFO):
        foo(token="apikey_123456")

    text = caplog.text
    assert "call.start" in text and "call.success" in text
    assert "trace-xyz" in text
    # key-based redaction wins → value becomes "****"
    assert "'token': '****'" in text
    # raw secret must never appear
    assert "apikey_123456" not in text


def test_retry_sync_eventually_succeeds():
    attempts = {"n": 0}

    @retry(retries=2, backoff_base=0.01, backoff_factor=1.0, jitter=0.0)
    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("boom")
        return 42

    t0 = time.perf_counter()
    assert flaky() == 42 and attempts["n"] == 3 and (time.perf_counter() - t0) < 0.2


def test_retry_async_eventually_succeeds():
    attempts = {"n": 0}

    @retry(retries=2, backoff_base=0.005, backoff_factor=1.0, jitter=0.0)
    async def flaky_async():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("boom")
        await asyncio.sleep(0.001)
        return "ok"

    assert asyncio.run(flaky_async()) == "ok"
    assert attempts["n"] == 3
