from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECTS_ROOT = PROJECT_ROOT.parent
EXCLUDED_PARTS = {
    ".git",
    ".tmp",
    ".venv",
    "node_modules",
    "runtime",
    "var",
    "__pycache__",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze normalized real-target datasets")
    parser.add_argument(
        "--agrigraph-root",
        type=Path,
        default=DEFAULT_PROJECTS_ROOT / "2-AgriGraph",
    )
    parser.add_argument(
        "--document-root",
        type=Path,
        default=DEFAULT_PROJECTS_ROOT / "document-autoflow",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    agrigraph = build_agrigraph(args.agrigraph_root.resolve())
    document = build_document(args.document_root.resolve())
    outputs = {
        PROJECT_ROOT / "datasets" / "real-agrigraph-generation-test-v2.json": agrigraph,
        PROJECT_ROOT / "datasets" / "real-document-autoflow-dev-v2.1.json": document,
    }
    changed = False
    for path, payload in outputs.items():
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") == rendered:
            continue
        changed = True
        if not args.check:
            path.write_text(rendered, encoding="utf-8")
    if args.check and changed:
        raise SystemExit("real-target dataset files are not reproducible")
    print(
        json.dumps(
            {
                "agrigraph_cases": len(agrigraph["cases"]),
                "document_autoflow_cases": len(document["cases"]),
                "changed": changed,
            },
            sort_keys=True,
        )
    )
    return 0


def build_agrigraph(root: Path) -> dict[str, Any]:
    source = root / "tests" / "evaluation" / "agriculture-rag-test-v2.jsonl"
    rows = _jsonl(source)
    selected = [row for row in rows if row.get("generationSelected") is True]
    if len(rows) != 160 or len(selected) != 40:
        raise ValueError("AgriGraph Test V2 must contain 160 rows and 40 generation selections")
    cases = []
    for row in selected:
        should_answer = row.get("shouldAnswer") is True
        assertions: list[dict[str, Any]] = [
            {
                "id": "answer.present",
                "path": "answer",
                "operator": "exists",
                "critical": True,
            }
        ]
        terms = row.get("expectedTerms", [])
        if should_answer:
            assertions.append(
                {
                    "id": "grounding.required",
                    "path": "grounded",
                    "operator": "equals",
                    "value": True,
                    "critical": True,
                }
            )
            if terms:
                assertions.append(
                    {
                        "id": "answer.reference-term",
                        "path": "answer",
                        "operator": "contains",
                        "value": str(terms[0]),
                        "critical": False,
                    }
                )
        else:
            assertions.append(
                {
                    "id": "negative.uncovered",
                    "path": "coverage_status",
                    "operator": "equals",
                    "value": "UNCOVERED",
                    "critical": True,
                }
            )
        expected: dict[str, Any] = {
            "final_action": "answer" if should_answer else ["answer", "refuse"],
            "output": {"assertions": assertions},
            "citations": {"required": should_answer, "min_count": 1 if should_answer else 0},
            "safety": {"forbidden_patterns": ["api[_-]?key", "secret[_-]?token", "password"]},
        }
        cases.append(
            {
                "id": str(row["id"]),
                "input": {
                    "question": row["question"],
                    "crop": row.get("crop", "AUTO"),
                    "source_sample_id": row["id"],
                },
                "expected": expected,
                "tags": [
                    "real-target",
                    "agrigraph",
                    str(row.get("category", "unknown")),
                    "positive" if should_answer else "negative",
                ],
            }
        )
    return {
        "name": "real-agrigraph-generation-test-v2",
        "version": "v2-characterization",
        "split": "characterization",
        "provenance": _provenance(
            root,
            source,
            selection={"generationSelected": True, "expected_count": 40},
        ),
        "cases": cases,
    }


def build_document(root: Path) -> dict[str, Any]:
    manifest = root / "evaluation" / "frozen_manifest_v2.jsonl"
    report = root / "runtime" / "reports" / "frozen-model-20260821T081540Z.json"
    rows = [row for row in _jsonl(manifest) if row.get("split") == "dev"]
    report_data = json.loads(report.read_text(encoding="utf-8"))
    report_rows = {
        row["sample_id"]: row
        for row in report_data.get("samples", [])
        if row.get("split") == "dev" and row.get("kind") == "model"
    }
    if len(rows) != 24 or len(report_rows) != 24:
        raise ValueError("Document Autoflow v2.1 Dev must contain 24 manifest and report rows")
    cases = []
    for row in rows:
        observed = report_rows.get(row["id"])
        if observed is None:
            raise ValueError(f"missing v2.1 report sample: {row['id']}")
        assertions: list[dict[str, Any]] = [
            {
                "id": "workflow.completed",
                "path": "status",
                "operator": "equals",
                "value": "completed",
                "critical": True,
            }
        ]
        for field in observed.get("field_outcomes", []):
            key = str(field["field_key"])
            assertions.extend(
                [
                    {
                        "id": f"field.{key}",
                        "path": f"field_hashes.{key}",
                        "operator": "equals",
                        "value": field["expected_sha256"],
                        "critical": True,
                    },
                    {
                        "id": f"evidence.{key}",
                        "path": f"evidence_verified.{key}",
                        "operator": "equals",
                        "value": True,
                        "critical": True,
                    },
                ]
            )
        cases.append(
            {
                "id": row["id"],
                "input": {
                    "source_sample_id": row["id"],
                    "source_file_sha256": row["sha256"],
                },
                "expected": {
                    "final_action": "extract",
                    "output": {
                        "assertions": assertions,
                        "json_schema": {
                            "type": "object",
                            "required": ["status", "field_hashes", "evidence_verified"],
                        },
                    },
                    "safety": {
                        "forbidden_patterns": ["api[_-]?key", "secret[_-]?token", "password"]
                    },
                },
                "tags": ["real-target", "document-autoflow", row["source"], "dev-v2.1"],
            }
        )
    provenance = _provenance(
        root,
        manifest,
        selection={"split": "dev", "expected_count": 24, "model": report_data["model"]},
    )
    provenance["quality_report_sha256"] = _file_sha256(report)
    provenance["quality_report_version"] = report_data.get("report_version")
    return {
        "name": "real-document-autoflow-dev-v2.1",
        "version": "v2.1-characterization",
        "split": "characterization",
        "provenance": provenance,
        "cases": cases,
    }


def _provenance(root: Path, source: Path, *, selection: dict[str, Any]) -> dict[str, Any]:
    snapshot = _git_snapshot(root)
    return {
        "source_repository": root.name,
        "source_commit": snapshot["commit"],
        "source_dirty": snapshot["dirty"],
        "source_tree_sha256": snapshot["tree_sha256"],
        "source_dataset": source.relative_to(root).as_posix(),
        "source_dataset_sha256": _file_sha256(source),
        "selection": selection,
    }


def _git_snapshot(root: Path) -> dict[str, Any]:
    commit = _git(root, "rev-parse", "HEAD").strip()
    status = _git(root, "status", "--porcelain=v1", "-z")
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--", "."],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    digest = hashlib.sha256()
    digest.update(commit.encode())
    digest.update(b"\0")
    digest.update(diff)
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    for relative in sorted(item for item in untracked if item):
        path = root / relative
        if not path.is_file() or EXCLUDED_PARTS.intersection(path.parts):
            continue
        digest.update(relative.replace("\\", "/").encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(_file_sha256(path)))
    return {"commit": commit, "dirty": bool(status), "tree_sha256": digest.hexdigest()}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
