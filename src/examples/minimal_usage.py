import logging
import sys
import asyncio
from trustgate.decorators import set_trace_id, log_call, retry

logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")


@log_call(
    include_args=True
)  # results are NOT logged unless you enable include_result=True
@retry(retries=2, backoff_base=0.05, backoff_factor=1.0, jitter=0.0)
def flaky(x: int) -> int:
    if x < 2:
        raise RuntimeError("boom")
    return x


async def main():
    set_trace_id("trace-123")
    print("result:", flaky(2))


asyncio.run(main())
