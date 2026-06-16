# Real-Host UAT Scripts

Phase 41 responsibility.

Purpose: Validate deferred v4.0 runtime confirmations on real hardware (not CI runners).
Prerequisite: `cd rust && cargo build --release`

| Script | Platform | Tests |
|--------|----------|-------|
| uat-01-concurrent-installer.sh | macOS | Concurrent port allocation race (UAT-01) |
| uat-02-runtime-props.sh | Linux | Debounce latency, PollWatcher promotion, rotation dedup (UAT-02) |
| uat-03-wsl-fallback.sh | WSL2 | PollWatcher fallback under WSL2 kernel (UAT-03) |

Note: uat-02 Check B (PollWatcher promotion) requires `sudo` to lower inotify watch limit.
Results go in `.planning/milestones/v5.0-UAT-REPORT.md`.
