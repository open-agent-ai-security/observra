#![no_main]

use libfuzzer_sys::fuzz_target;
use agent_telemetry_fwd::detection::safe_regex::compile_safe_pattern;

fuzz_target!(|data: &[u8]| {
    // Only fuzz valid UTF-8 strings — compile_safe_pattern takes &str
    if let Ok(pattern) = std::str::from_utf8(data) {
        // Must not panic — should return Ok or Err gracefully
        let _ = compile_safe_pattern(pattern, None);
    }
});
