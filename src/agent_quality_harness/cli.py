from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx


def gate_exit_code(decision: str) -> int:
    return 0 if decision.lower() in {"ship", "warn"} else 2


def _load_gate(args: argparse.Namespace) -> dict[str, Any]:
    if args.report is not None:
        return json.loads(Path(args.report).read_text(encoding="utf-8"))
    if args.run_id is None:
        raise ValueError("either --run-id or --report is required")
    response = httpx.get(
        f"{args.api_url.rstrip('/')}/api/v1/eval-runs/{args.run_id}/gate",
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def gate_command(args: argparse.Namespace) -> int:
    try:
        result = _load_gate(args)
        decision = str(result["decision"]).lower()
    except (OSError, ValueError, KeyError, json.JSONDecodeError, httpx.HTTPError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2
    print(f"Gate decision: {decision.upper()}")
    for reason in result.get("reasons", []):
        print(
            f"- {reason.get('severity', 'info').upper()}: "
            f"{reason.get('rule_id', 'unknown')} "
            f"(threshold={reason.get('threshold')}, actual={reason.get('actual')})"
        )
    if decision == "warn":
        print("::warning::Agent Quality Harness gate returned WARN")
    if decision == "block":
        print("::error::Agent Quality Harness gate returned BLOCK")
    return gate_exit_code(decision)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aqh")
    commands = parser.add_subparsers(dest="command", required=True)
    gate = commands.add_parser("gate", help="evaluate a persisted gate result")
    gate.add_argument("--run-id", type=int)
    gate.add_argument("--report", type=Path)
    gate.add_argument("--api-url", default="http://127.0.0.1:8000")
    gate.set_defaults(handler=gate_command)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(args.handler(args))


if __name__ == "__main__":
    main()
