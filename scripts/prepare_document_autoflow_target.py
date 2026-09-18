from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCUMENT_ROOT = PROJECT_ROOT.parent / "document-autoflow"


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a dedicated Document Autoflow target")
    parser.add_argument("--base-url", default="http://127.0.0.1:8030")
    parser.add_argument("--auth-ref", default="AQH_DOCUMENT_AUTOFLOW_AUTH")
    parser.add_argument("--document-root", type=Path, default=DEFAULT_DOCUMENT_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / ".tmp" / "document-autoflow-capabilities.json",
    )
    parser.add_argument("--parse-timeout-seconds", type=int, default=1800)
    parser.add_argument("--reuse-project-id")
    parser.add_argument("--reuse-template-id")
    parser.add_argument("--sample-limit", type=int)
    args = parser.parse_args()

    credentials = _credentials(args.auth_ref)
    root = args.document_root.resolve()
    manifest = [
        json.loads(line)
        for line in (root / "evaluation" / "frozen_manifest_v2.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    dev_rows = [row for row in manifest if row.get("split") == "dev"]
    report = json.loads(
        (root / "runtime" / "reports" / "frozen-model-20260821T081540Z.json").read_text(
            encoding="utf-8"
        )
    )
    report_rows = [
        row
        for row in report.get("samples", [])
        if row.get("split") == "dev" and row.get("kind") == "model"
    ]
    if len(dev_rows) != 24 or len(report_rows) != 24:
        raise ValueError("Document Autoflow v2.1 preparation requires exactly 24 Dev rows")
    if args.sample_limit:
        if args.sample_limit < 1 or args.sample_limit > len(dev_rows):
            raise ValueError("sample limit is outside the frozen Document Dataset")
        dev_rows = dev_rows[: args.sample_limit]
    field_keys = sorted(
        {str(field["field_key"]) for row in report_rows for field in row.get("field_outcomes", [])}
    )
    with httpx.Client(base_url=args.base_url, timeout=120) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": credentials["username"], "password": credentials["password"]},
        )
        if response.status_code >= 400:
            raise PermissionError("Document Autoflow preparation login rejected")
        if args.reuse_project_id:
            if not args.reuse_template_id:
                raise ValueError("--reuse-template-id is required with --reuse-project-id")
            project_id = args.reuse_project_id
            template_id = args.reuse_template_id
            project = client.get(f"/api/v1/projects/{project_id}")
            project.raise_for_status()
            documents = project.json().get("documents", [])
            by_sha = {item["sha256"]: item["id"] for item in documents}
            document_map = {
                row["id"]: by_sha[row["sha256"]] for row in dev_rows if row["sha256"] in by_sha
            }
            if len(document_map) != len(dev_rows):
                raise ValueError("reused project does not contain all 24 frozen document hashes")
        else:
            stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
            project = client.post(
                "/api/v1/projects",
                json={
                    "name": f"AQH characterization {stamp}",
                    "description": (
                        "Dedicated 24-case v2.1 characterization created by Agent Quality Harness."
                    ),
                },
            )
            project.raise_for_status()
            project_id = project.json()["id"]
            template = client.post(
                "/api/v1/templates",
                json={
                    "name": f"aqh_characterization_{stamp}",
                    "document_type": "characterization_document",
                    "fields": [
                        {
                            "key": key,
                            "label": key.replace("_", " "),
                            "value_type": "string",
                            "required": False,
                            "repeated": False,
                        }
                        for key in field_keys
                    ],
                    "rules": [],
                },
            )
            template.raise_for_status()
            template_id = template.json()["id"]
            published = client.post(f"/api/v1/templates/{template_id}/publish")
            published.raise_for_status()

            document_map = {}
            for row in dev_rows:
                source = root / row["file"]
                if _sha256(source) != row["sha256"]:
                    raise ValueError(f"source file hash mismatch: {row['id']}")
                with source.open("rb") as handle:
                    uploaded = client.post(
                        f"/api/v1/projects/{project_id}/documents",
                        files={"file": (source.name, handle, _media_type(source))},
                    )
                uploaded.raise_for_status()
                document_map[row["id"]] = uploaded.json()["id"]

        deadline = time.monotonic() + args.parse_timeout_seconds
        pending = set(document_map)
        failures: dict[str, str] = {}
        while pending:
            for sample_id in list(pending):
                item = client.get(f"/api/v1/documents/{document_map[sample_id]}")
                item.raise_for_status()
                status = str(item.json()["status"]).lower()
                if status == "parsed":
                    pending.remove(sample_id)
                elif status == "failed":
                    failures[sample_id] = str(item.json().get("error_type", "unknown"))
                    pending.remove(sample_id)
            if failures:
                raise RuntimeError(f"Document Autoflow parsing failed for {sorted(failures)}")
            if pending and time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Document Autoflow parsing timed out with {len(pending)} pending"
                )
            if pending:
                time.sleep(2)

    payload = {
        "contract_profile": "document_autoflow_v1",
        "project_id": project_id,
        "template_id": template_id,
        "document_map": document_map,
        "poll_interval_seconds": 2,
        "max_poll_seconds": 360,
        "case_time_limit_seconds": 390,
        "stop_on_routes": ["REPROCESS"],
        "budget": {
            "max_requests": 240,
            "max_input_tokens": 3_000_000,
            "max_output_tokens": 500_000,
            "max_cost_usd": 1,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "project_id": project_id,
                "template_id": template_id,
                "document_count": len(document_map),
                "capabilities_path": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


def _credentials(auth_ref: str) -> dict[str, str]:
    raw = os.getenv(auth_ref)
    if raw is None:
        raise RuntimeError(f"auth reference environment variable is not set: {auth_ref}")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("type") != "cookie_login":
        raise ValueError("Document Autoflow preparation requires cookie_login auth")
    username, password = value.get("username"), value.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise ValueError("Document Autoflow preparation credentials are incomplete")
    return {"username": username, "password": password}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _media_type(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".pdf": "application/pdf",
    }.get(path.suffix.lower(), "application/octet-stream")


if __name__ == "__main__":
    raise SystemExit(main())
