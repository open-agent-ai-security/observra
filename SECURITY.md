<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x (latest minor) | Yes |
| < 1.0 | No |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Use GitHub Security Advisories to report vulnerabilities privately:

1. Go to the [Security tab](https://github.com/open-agent-ai-security/observra/security) of this repository
2. Click "Report a vulnerability"
3. Fill in the vulnerability details

If GitHub Security Advisories are unavailable to you for any reason, email **developer@exabeam.com** with the subject line **`observra security report`** and the same level of detail.

### What We Consider a Security Issue

- Data confidentiality: telemetry data exfiltration, credential leakage through event capture
- Data integrity: event tampering, injection of false telemetry events
- PII exposure: failure of the redaction engine to mask sensitive data

### Response Timeline

- **Acknowledgement:** within 48 hours
- **Initial assessment:** within 7 days
- **Fix development:** critical (days), high (weeks), medium (next minor release)
