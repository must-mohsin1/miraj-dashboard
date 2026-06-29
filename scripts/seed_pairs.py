#!/usr/bin/env python3
"""Seed the watchlist with default 15-20 trading pairs.

Usage:
    python scripts/seed_pairs.py              # print to stdout
    python scripts/seed_pairs.py --save       # save to a JSON file
    python scripts/seed_pairs.py --api URL     # POST to backend API

The backend exposes POST /api/v1/watchlist to bulk-import pairs.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# ── Default pairs ──────────────────────────────────────────────────────────
DEFAULT_PAIRS: list[dict[str, Any]] = [
    {"pair": "BTC-USD",   "timeframe": "4h", "active": True},
    {"pair": "ETH-USD",   "timeframe": "4h", "active": True},
    {"pair": "BNB-USD",   "timeframe": "4h", "active": True},
    {"pair": "SOL-USD",   "timeframe": "4h", "active": True},
    {"pair": "XRP-USD",   "timeframe": "4h", "active": True},
    {"pair": "ADA-USD",   "timeframe": "4h", "active": True},
    {"pair": "DOGE-USD",  "timeframe": "1d", "active": True},
    {"pair": "DOT-USD",   "timeframe": "4h", "active": True},
    {"pair": "LINK-USD",  "timeframe": "4h", "active": True},
    {"pair": "AVAX-USD",  "timeframe": "4h", "active": True},
    {"pair": "MATIC-USD", "timeframe": "4h", "active": True},
    {"pair": "ATOM-USD",  "timeframe": "4h", "active": True},
    {"pair": "LTC-USD",   "timeframe": "1d", "active": True},
    {"pair": "FIL-USD",   "timeframe": "4h", "active": True},
    {"pair": "ARB-USD",   "timeframe": "4h", "active": True},
    {"pair": "OP-USD",    "timeframe": "4h", "active": True},
    {"pair": "INJ-USD",   "timeframe": "4h", "active": True},
    {"pair": "TIA-USD",   "timeframe": "4h", "active": True},
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed default watchlist pairs.")
    parser.add_argument("--save", type=str, help="Save pairs to a JSON file")
    parser.add_argument("--api", type=str, help="POST pairs to backend API URL")
    args = parser.parse_args()

    if args.save:
        with open(args.save, "w") as f:
            json.dump(DEFAULT_PAIRS, f, indent=2)
        print(f"Saved {len(DEFAULT_PAIRS)} pairs to {args.save}")
    elif args.api:
        import requests

        resp = requests.post(
            f"{args.api.rstrip('/')}/api/v1/watchlist",
            json={"pairs": DEFAULT_PAIRS},
            timeout=30,
        )
        if resp.status_code in (200, 201):
            print(f"Imported {len(DEFAULT_PAIRS)} pairs via {args.api}")
        else:
            print(f"Failed: {resp.status_code} — {resp.text}", file=sys.stderr)
            sys.exit(1)
    else:
        print(json.dumps(DEFAULT_PAIRS, indent=2))


if __name__ == "__main__":
    main()
