# Property-Based Parity Tests

Phase 28 active responsibility.

## Running

```bash
# Build Rust oracle
cargo build --manifest-path tests/property/Cargo.toml --release --bin parity-oracle

# Run Python parity tests
pytest tests/property/test_parity.py

# Run Rust property tests
cargo test --manifest-path tests/property/Cargo.toml
```

## Architecture

- Rust `proptest` generates random valid `TelemetryEvent`-shaped values.
- Python `oracle.py` reconstructs via `agent_telemetry.core.events.create_event()` and re-serializes.
- Contract: byte-identical JSON output.
