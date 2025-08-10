from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from contextvars import ContextVar
from typing import (
    Any,
    Callable,
    Optional,
    ParamSpec,
    TypeVar,
    Tuple,
    Type,
)

P = ParamSpec("P")
T = TypeVar("T")

# --------- tracing (propagates across your app) ----------
_trace_id: ContextVar[Optional[str]] = ContextVar("_trace_id", default=None)


def set_trace_id(trace_id: Optional[str]) -> None:
    _trace_id.set(trace_id)


def get_trace_id() -> Optional[str]:
    return _trace_id.get()


# --------- minimal redactor (override in @log_call) ----------
def default_redactor(obj: Any) -> Any:
    """
    Replace obvious secrets; keep payload sizes small.
    Extend this in prod (e.g., hash emails/phones).
    """
    if isinstance(obj, str):
        s = obj
        s = s.replace("Bearer ", "Bearer ****")
        s = s.replace("apikey_", "apikey_****")
        return s if len(s) <= 256 else s[:256] + "…"
    if isinstance(obj, (bytes, bytearray)):
        return f"<{type(obj).__name__} len={len(obj)}>"
    if isinstance(obj, (list, tuple)):
        return type(obj)(default_redactor(x) for x in obj)  # type: ignore
    if isinstance(obj, dict):
        redacted = {}
        for k, v in obj.items():
            k2 = k.lower()
            if k2 in {
                "password",
                "secret",
                "token",
                "authorization",
                "api_key",
                "apikey",
            }:
                redacted[k] = "****"
            else:
                redacted[k] = default_redactor(v)
        return redacted
    return obj


# --------- logging decorator ----------
def log_call(
    *,
    logger: Optional[logging.Logger] = None,
    level: int = logging.INFO,
    include_args: bool = True,
    include_result: bool = False,
    redact: Callable[[Any], Any] = default_redactor,
    name: Optional[str] = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Structured logging with duration + outcome.
    - include_result=False by default (privacy).
    - redact: pluggable sanitizer.
    """
    lg = logger or logging.getLogger("app")

    def _decorator(fn: Callable[P, T]) -> Callable[P, T]:
        fn_name = name or fn.__qualname__

        @functools.wraps(fn)
        def _sync(*args: P.args, **kwargs: P.kwargs) -> T:
            start = time.perf_counter()
            trace = get_trace_id()
            if include_args:
                safe_args = redact(args)
                safe_kwargs = redact(kwargs)
                lg.log(
                    level,
                    {
                        "event": "call.start",
                        "fn": fn_name,
                        "trace_id": trace,
                        "args": safe_args,
                        "kwargs": safe_kwargs,
                    },
                )
            else:
                lg.log(level, {"event": "call.start", "fn": fn_name, "trace_id": trace})

            try:
                result = fn(*args, **kwargs)
                dur = round((time.perf_counter() - start) * 1000, 2)
                payload: dict[str, Any] = {
                    "event": "call.success",
                    "fn": fn_name,
                    "trace_id": trace,
                    "ms": dur,
                }
                if include_result:
                    payload["result"] = redact(result)
                lg.log(level, payload)
                return result
            except Exception as e:
                dur = round((time.perf_counter() - start) * 1000, 2)
                lg.exception(
                    {
                        "event": "call.error",
                        "fn": fn_name,
                        "trace_id": trace,
                        "ms": dur,
                        "error": str(e),
                    }
                )
                raise

        @functools.wraps(fn)
        async def _async(*args: P.args, **kwargs: P.kwargs) -> T:  # type: ignore[override]
            start = time.perf_counter()
            trace = get_trace_id()
            if include_args:
                safe_args = redact(args)
                safe_kwargs = redact(kwargs)
                lg.log(
                    level,
                    {
                        "event": "call.start",
                        "fn": fn_name,
                        "trace_id": trace,
                        "args": safe_args,
                        "kwargs": safe_kwargs,
                    },
                )
            else:
                lg.log(level, {"event": "call.start", "fn": fn_name, "trace_id": trace})

            try:
                result = await fn(*args, **kwargs)  # type: ignore[misc]
                dur = round((time.perf_counter() - start) * 1000, 2)
                payload: dict[str, Any] = {
                    "event": "call.success",
                    "fn": fn_name,
                    "trace_id": trace,
                    "ms": dur,
                }
                if include_result:
                    payload["result"] = redact(result)
                lg.log(level, payload)
                return result
            except Exception as e:
                dur = round((time.perf_counter() - start) * 1000, 2)
                lg.exception(
                    {
                        "event": "call.error",
                        "fn": fn_name,
                        "trace_id": trace,
                        "ms": dur,
                        "error": str(e),
                    }
                )
                raise

        # pick async or sync wrapper
        return _async if asyncio.iscoroutinefunction(fn) else _sync  # type: ignore[return-value]

    return _decorator


# --------- retry decorator ----------
def retry(
    *,
    retries: int = 3,
    backoff_base: float = 0.25,  # seconds
    backoff_factor: float = 2.0,
    jitter: float = 0.1,  # add up to +/-10% jitter
    retry_on: Tuple[Type[BaseException], ...] = (Exception,),
    give_up_on: Tuple[Type[BaseException], ...] = (asyncio.CancelledError,),
    logger: Optional[logging.Logger] = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Exponential backoff with jitter; async/sync aware.
    - retries counts *failures* (total attempts = retries+1)
    - give_up_on: never retry (e.g., CancelledError)
    """
    lg = logger or logging.getLogger("app")

    def _decorator(fn: Callable[P, T]) -> Callable[P, T]:
        fn_name = fn.__qualname__

        def _sleep_s(d: float) -> None:
            time.sleep(d)

        async def _sleep_a(d: float) -> None:
            await asyncio.sleep(d)

        def _delay(i: int) -> float:
            base = backoff_base * (backoff_factor**i)
            jitter_amt = base * random.uniform(-jitter, jitter)
            return max(0.0, base + jitter_amt)

        @functools.wraps(fn)
        def _sync(*args: P.args, **kwargs: P.kwargs) -> T:
            attempt = 0
            while True:
                try:
                    return fn(*args, **kwargs)
                except give_up_on as e:  # type: ignore[misc]
                    lg.warning(
                        {
                            "event": "retry.giveup",
                            "fn": fn_name,
                            "attempt": attempt,
                            "error": str(e),
                        }
                    )
                    raise
                except retry_on as e:  # type: ignore[misc]
                    if attempt >= retries:
                        lg.error(
                            {
                                "event": "retry.exhausted",
                                "fn": fn_name,
                                "attempt": attempt,
                                "error": str(e),
                            }
                        )
                        raise
                    delay = _delay(attempt)
                    lg.info(
                        {
                            "event": "retry.wait",
                            "fn": fn_name,
                            "attempt": attempt + 1,
                            "sleep_s": round(delay, 3),
                        }
                    )
                    _sleep_s(delay)
                    attempt += 1

        @functools.wraps(fn)
        async def _async(*args: P.args, **kwargs: P.kwargs) -> T:  # type: ignore[override]
            attempt = 0
            while True:
                try:
                    return await fn(*args, **kwargs)  # type: ignore[misc]
                except give_up_on as e:  # type: ignore[misc]
                    lg.warning(
                        {
                            "event": "retry.giveup",
                            "fn": fn_name,
                            "attempt": attempt,
                            "error": str(e),
                        }
                    )
                    raise
                except retry_on as e:  # type: ignore[misc]
                    if attempt >= retries:
                        lg.error(
                            {
                                "event": "retry.exhausted",
                                "fn": fn_name,
                                "attempt": attempt,
                                "error": str(e),
                            }
                        )
                        raise
                    delay = _delay(attempt)
                    lg.info(
                        {
                            "event": "retry.wait",
                            "fn": fn_name,
                            "attempt": attempt + 1,
                            "sleep_s": round(delay, 3),
                        }
                    )
                    await _sleep_a(delay)
                    attempt += 1

        return _async if asyncio.iscoroutinefunction(fn) else _sync  # type: ignore[return-value]

    return _decorator
