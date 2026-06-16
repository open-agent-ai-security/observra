mod telemetry_event;

use std::io::{self, BufRead};
use telemetry_event::ParityEvent;

fn main() {
    let stdin = io::stdin();
    let line = stdin.lock().lines().next().unwrap().unwrap();
    let event: ParityEvent = serde_json::from_str(&line).expect("valid ParityEvent JSON");
    println!("{}", serde_json::to_string(&event).expect("serialize"));
}
