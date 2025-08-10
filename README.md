### TrustGate
# TrustGate
**Compliance-by-design guardrails for Python services** — traceability, privacy-safe logging, and resilient calls (sync + async). Framework-agnostic and FastAPI-friendly.

> Ship APIs and LLM gateways with compliance, security, and reliability baked in from day one.

## Why TrustGate?
Most services log too much, retry too aggressively, and lack traceability. That creates risk:
- PII/API keys leaking into logs
- No end-to-end trace ID for forensics
- Thundering herds hammering dependencies

**TrustGate** provides a tiny set of decorators that flip the defaults:
- **Privacy by default** (redaction, result logging off by default)
- **Traceability** (ContextVar trace IDs on every call)
- **Resilience** (retries with exponential backoff + jitter)

## Features (v0.1)
- `set_trace_id / get_trace_id` — async-safe trace context (ContextVar)
- `@log_call` — structured logs with duration; optional args/result; **pluggable redaction**
- `@retry` — exponential backoff + jitter; sync & async; `give_up_on` for non-retriables

> Roadmap (v0.1.x / v0.2): `timeout`, `no_bearer_in_args`, `max_payload_size`, `schema_validate`, `audit_log`, `circuit_breaker`, `rate_limit`.

## Quickstart

### Install (dev workflow with `uv`)

uv venv
uv sync --dev

### Design principles
- **Compliance by default**: nothing sensitive in logs unless explicitly allowed.

- **Type-safe & async-aware**: ParamSpec/TypeVar, preserves signatures, works for sync/async.

- **Composable**: small, focused decorators you can stack.

### Contributing
- Issues and PRs welcome. Keep changes small and add tests:

- Unit tests with pytest

- Type checking with pyright

- Lint/format with ruff and black

### License
- MIT