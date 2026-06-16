pub mod telemetry_event;

use std::process::{Command, Stdio};
use std::io::Write;
use proptest::prelude::*;
use telemetry_event::ParityEvent;

fn event_type_strategy() -> impl Strategy<Value = String> {
    prop_oneof![
        Just("session_start".to_string()),
        Just("session_end".to_string()),
        Just("user".to_string()),
        Just("user_message".to_string()),
        Just("model_request".to_string()),
        Just("model_response".to_string()),
        Just("model_error".to_string()),
        Just("turn".to_string()),
        Just("turn_duration".to_string()),
        Just("compact_boundary".to_string()),
        Just("tool_start".to_string()),
        Just("tool_end".to_string()),
        Just("tool_error".to_string()),
        Just("agent_start".to_string()),
        Just("agent_end".to_string()),
        Just("agent_handoff".to_string()),
        Just("agent_handoff_error".to_string()),
        Just("stream_event".to_string()),
        Just("adapter_close".to_string()),
        Just("forwarder_update_available".to_string()),
        Just("forwarder_updated".to_string()),
        Just("forwarder_update_failed".to_string()),
    ]
}

fn arb_parity_event() -> impl Strategy<Value = ParityEvent> {
    (
        event_type_strategy(),
        prop_oneof![
            Just(None),
            Just(Some("read_file".to_string())),
            Just(Some("delete_file".to_string())),
            Just(Some("bash".to_string())),
        ],
        prop_oneof![
            Just(None),
            Just(Some("claude-opus-4-7".to_string())),
            Just(Some("gpt-4o".to_string())),
            Just(Some("gemini-2.5-pro".to_string())),
        ],
        prop_oneof![
            Just(Some("claude_code".to_string())),
            Just(Some("openai".to_string())),
            Just(Some("gemini_cli".to_string())),
        ],
    )
    .prop_map(|(event_type, tool_name, model_name, framework)| {
        let action = match event_type.as_str() {
            "session_start" => "start_session",
            "session_end" => "end_session",
            "user" | "user_message" => "prompt_submit",
            "turn" | "turn_duration" | "model_response" | "model_error" => "call_llm",
            "compact_boundary" => "compact_context",
            "tool_start" | "tool_end" | "tool_error" => "tool_call",
            "agent_start" | "agent_end" | "agent_handoff" | "agent_handoff_error" => "invoke_agent",
            "forwarder_update_available" => "update_available",
            "forwarder_updated" => "update_applied",
            "forwarder_update_failed" => "update_failed",
            _ => "unknown",
        };
        let vendor = match model_name.as_deref() {
            Some(m) if m.contains("claude") || m.contains("anthropic") => "anthropic",
            Some(m) if m.contains("gpt") || m.contains("o1") || m.contains("o3") || m.contains("openai") => "openai",
            Some(m) if m.contains("gemini") || m.contains("google") || m.contains("vertex") => "google",
            Some(m) if m.contains("copilot") => "microsoft",
            _ => "unknown",
        };
        let result = match event_type.as_str() {
            "tool_end" | "agent_end" | "turn" | "model_response" => Some("success"),
            "tool_error" | "model_error" => Some("failure"),
            _ => None,
        };
        let mut data = serde_json::Map::new();
        data.insert("action".to_string(), serde_json::Value::String(action.to_string()));
        data.insert("vendor".to_string(), serde_json::Value::String(vendor.to_string()));
        if let Some(r) = result {
            data.insert("result".to_string(), serde_json::Value::String(r.to_string()));
        }
        if let Some(ref t) = tool_name {
            let reversible = if t.contains("delete") || t.contains("drop") || t.contains("remove") {
                Some(false)
            } else if t.contains("read") || t.contains("fetch") || t.contains("list") {
                Some(true)
            } else {
                None
            };
            if let Some(rev) = reversible {
                data.insert("reversible".to_string(), serde_json::Value::Bool(rev));
            }
        }

        ParityEvent {
            event_id: "01HZTEST000000000000000000".to_string(),
            timestamp: 1714500000.0,
            trace_id: "trace-test-01".to_string(),
            session_id: "sess-test-01".to_string(),
            span_id: "span-test-01".to_string(),
            event_type,
            agent_name: None,
            tool_name,
            model_name,
            data: Some(serde_json::Value::Object(data)),
            framework: framework.clone(),
            skill_name: None,
            host: Some("test-host".to_string()),
            user: Some("test-user".to_string()),
            os: Some("Linux".to_string()),
            arch: Some("x86_64".to_string()),
            library_version: Some("2.1.0".to_string()),
        }
    })
}

proptest! {
    #[test]
    fn parity_roundtrip(event in arb_parity_event()) {
        let rust_json = serde_json::to_string(&event).unwrap();

        let mut python = Command::new("python3")
            .arg("oracle.py")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .expect("spawn python oracle");

        {
            let mut stdin = python.stdin.take().unwrap();
            writeln!(&mut stdin, "{}", rust_json).unwrap();
        }

        let output = python.wait_with_output().unwrap();
        assert!(
            output.status.success(),
            "python oracle failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );

        let python_json = String::from_utf8(output.stdout).unwrap().trim().to_string();
        prop_assert_eq!(
            rust_json, python_json,
            "byte mismatch between Rust and Python serialization"
        );
    }
}
