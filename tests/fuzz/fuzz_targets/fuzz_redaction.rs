#![no_main]

use libfuzzer_sys::fuzz_target;
use agent_telemetry_fwd::detection::redaction::redact_string;

fuzz_target!(|data: &[u8]| {
    // Only fuzz valid UTF-8 strings — redact_string takes &str
    if let Ok(text) = std::str::from_utf8(data) {
        // Must not panic on any input
        let _ = redact_string(text);
    }
});
