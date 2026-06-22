#!/usr/bin/env python3
"""Simple roundtrip oracle: parse JSON, strip None, emit canonical JSON."""

import json
import sys


def strip_none_values(d):
    """Recursively strip dict keys whose value is None."""
    out = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, dict):
            nested = strip_none_values(v)
            if nested:
                out[k] = nested
        elif isinstance(v, list):
            out[k] = [strip_none_values(i) if isinstance(i, dict) else i for i in v if i is not None]
        else:
            out[k] = v
    return out


def main():
    raw = sys.stdin.readline()
    obj = json.loads(raw)
    result = json.dumps(
        strip_none_values(obj),
        separators=(",", ":"),
        ensure_ascii=False,
    )
    sys.stdout.write(result)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
