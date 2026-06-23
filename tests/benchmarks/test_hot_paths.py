# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Phase 39 -- pytest-benchmark tests for Python hot paths (PERF-07).

Four benchmarks exercising the performance-critical functions:
1. test_bench_submit_batch -- PooledWriter.submit_batch submission overhead
2. test_bench_redaction_pipeline -- Redactor.redact_dict on realistic payload
3. test_bench_cost_calculation -- CostCalculator.calculate_cost for a single LLM call
4. test_bench_contextvar_propagation -- ContextVar set/get/reset cycle

Per D-03: benchmarks target the underlying functions used in async pipelines.
All 4 functions are synchronous at the call site -- no asyncio.run() wrapper needed.
"""

from __future__ import annotations


def test_bench_submit_batch(benchmark, tmp_path, realistic_batch):
    """Benchmark PooledWriter.submit_batch submission overhead (PERF-07).

    submit_batch is synchronous (returns None, submits to ProcessPoolExecutor).
    This measures the submission path: semaphore acquire + future submit.
    """
    from observra.core.pool_writer import PooledWriter

    pw = PooledWriter(
        backend_type="jsonl",
        backend_kwargs={"path": str(tmp_path / "bench.jsonl")},
        max_workers=2,
        batch_timeout=0.5,
    )

    benchmark.pedantic(
        pw.submit_batch,
        args=(realistic_batch,),
        warmup_rounds=2,
        rounds=20,
        iterations=1,
    )
    pw.close()


def test_bench_redaction_pipeline(benchmark):
    """Benchmark Redactor.redact_dict on a realistic payload (PERF-07).

    Tests the regex-based PII redaction pipeline on a dict containing
    a JWT, email, and session ID -- representative of production payloads.
    """
    from observra.core.redaction import Redactor

    redactor = Redactor()
    payload = {
        "tool_input": "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
        "user_email": "user@example.com",
        "session_id": "sess-abc-123",
    }

    benchmark.pedantic(
        redactor.redact_dict,
        args=(payload,),
        warmup_rounds=3,
        rounds=100,
        iterations=5,
    )


def test_bench_cost_calculation(benchmark):
    """Benchmark CostCalculator.calculate_cost for a single LLM call (PERF-07).

    CostCalculator is synchronous. Tests the pricing lookup + Decimal math path.
    """
    from observra.core.cost import CostCalculator

    calc = CostCalculator()
    result = benchmark(
        calc.calculate_cost,
        model_name="claude-opus-4-5",
        input_tokens=500,
        output_tokens=200,
    )
    assert result is not None


def test_bench_contextvar_propagation(benchmark):
    """Benchmark ContextVar set/get/reset cycle for trace propagation (PERF-07).

    Measures the overhead of the ContextVar-based trace/session propagation
    that runs on every event capture path.
    """
    from observra.core.context import session_id_var, trace_id_var

    def run_propagation():
        token1 = trace_id_var.set("trace-abc-123")
        token2 = session_id_var.set("session-xyz-456")
        _ = trace_id_var.get()
        _ = session_id_var.get()
        trace_id_var.reset(token1)
        session_id_var.reset(token2)

    benchmark.pedantic(
        run_propagation,
        warmup_rounds=5,
        rounds=50,
        iterations=10,
    )
