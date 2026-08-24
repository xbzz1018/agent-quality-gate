from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from agent_quality_harness.administration import bootstrap_platform_admin
from agent_quality_harness.core.config import get_settings
from agent_quality_harness.core.database import Database


def gate_exit_code(decision: str) -> int:
    return 0 if decision.lower() in {"ship", "warn"} else 2


def _load_gate(args: argparse.Namespace) -> dict[str, Any]:
    if args.report is not None:
        return json.loads(Path(args.report).read_text(encoding="utf-8"))
    if args.run_id is None:
        raise ValueError("either --run-id or --report is required")
    headers = {} if args.api_key is None else {"X-API-Key": args.api_key}
    if args.organization_id is not None:
        headers["X-Organization-ID"] = str(args.organization_id)
    response = httpx.get(
        f"{args.api_url.rstrip('/')}/api/v1/eval-runs/{args.run_id}/gate",
        headers=headers,
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


def admin_bootstrap_command(args: argparse.Namespace) -> int:
    if not args.password_stdin:
        print("FAILED: --password-stdin is required", file=sys.stderr)
        return 2
    password = sys.stdin.readline().rstrip("\r\n")
    if not password:
        print("FAILED: password stdin was empty", file=sys.stderr)
        return 2
    database = Database(get_settings().database_url)
    try:
        with database.session() as session:
            user = bootstrap_platform_admin(
                session,
                username=args.username,
                password=password,
                display_name=args.display_name or args.username,
                email=args.email,
            )
        print(f"Platform administrator created: {user.username} (id={user.id})")
        return 0
    except (LookupError, ValueError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2
    finally:
        database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aqh")
    commands = parser.add_subparsers(dest="command", required=True)
    gate = commands.add_parser("gate", help="evaluate a persisted gate result")
    gate.add_argument("--run-id", type=int)
    gate.add_argument("--report", type=Path)
    gate.add_argument("--api-url", default="http://127.0.0.1:8000")
    gate.add_argument("--api-key", default=os.getenv("AQH_API_KEY"))
    gate.add_argument("--organization-id", type=int)
    gate.set_defaults(handler=gate_command)
    admin = commands.add_parser("admin", help="platform administration")
    admin_commands = admin.add_subparsers(dest="admin_command", required=True)
    bootstrap = admin_commands.add_parser("bootstrap", help="create the first administrator")
    bootstrap.add_argument("--username", required=True)
    bootstrap.add_argument("--display-name")
    bootstrap.add_argument("--email")
    bootstrap.add_argument("--password-stdin", action="store_true")
    bootstrap.set_defaults(handler=admin_bootstrap_command)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(args.handler(args))


if __name__ == "__main__":
    main()
