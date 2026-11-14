"""Regenerate Docker dependency locks, or verify them without changing the tree."""
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("api", "runtime", "deep-agent", "distributed", "fake-http", "fake-ag-ui")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="write updated locks")
    parser.add_argument("--profile", choices=PROFILES, action="append")
    args = parser.parse_args()
    for profile in args.profile or PROFILES:
        source = ROOT / f"requirements-{profile}.txt"
        lock = source.with_suffix(".lock")
        with tempfile.TemporaryDirectory() as temporary:
            output = lock if args.update else Path(temporary) / lock.name
            command = [
                "uv", "pip", "compile", str(source), "--python-version", "3.12",
                "--universal", "--no-header", "--no-annotate", "--quiet",
                "--output-file", str(output),
            ]
            if not args.update:
                command.extend(["--constraint", str(lock)])
            result = subprocess.run(command, cwd=ROOT, check=False)
            if result.returncode:
                return result.returncode
            if not args.update and output.read_text() != lock.read_text():
                print(f"{lock.name} is stale; run python scripts/runtime_locks.py --update")
                return 1
        print(f"{profile}: {'updated' if args.update else 'verified'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
