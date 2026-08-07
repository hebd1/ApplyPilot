#!/usr/bin/env python3
"""Smoke-test CapSolver API key via getBalance.

Usage (WSL):
  .venv/bin/python scripts/test_capsolver.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from applypilot import config


def get_balance(api_key: str) -> dict:
    payload = json.dumps({"clientKey": api_key}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.capsolver.com/getBalance",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    config.load_env()
    key = os.environ.get("CAPSOLVER_API_KEY", "").strip()
    if not key:
        print("FAIL: CAPSOLVER_API_KEY not set in ~/.applypilot/.env")
        return 1

    print(f"Key present (len={len(key)}, prefix={key[:6]}...)")
    try:
        data = get_balance(key)
    except urllib.error.HTTPError as exc:
        print(f"FAIL: HTTP {exc.code}: {exc.read()[:200]!r}")
        return 1
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    error_id = data.get("errorId", -1)
    if error_id != 0:
        print(f"FAIL: errorId={error_id} errorCode={data.get('errorCode')} "
              f"errorDescription={data.get('errorDescription')}")
        return 1

    balance = data.get("balance")
    print(f"OK: CapSolver balance=${balance}")
    if balance is not None and float(balance) <= 0:
        print("WARN: balance is zero — createTask may return ERROR_ZERO_BALANCE")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
