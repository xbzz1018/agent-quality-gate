from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agent_quality_harness.domain.models import (
    AgentVersion,
    AgentVersionSkill,
    EvalRun,
    EvaluationTarget,
    SkillPackage,
    SkillScan,
    SkillVersion,
)

MAX_SKILL_FILES = 100
MAX_SKILL_BYTES = 1024 * 1024
SCANNER_VERSION = "skills-static-v1"

_KNOWN_SUFFIXES = {
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".py",
    ".js",
    ".ts",
    ".sh",
    ".ps1",
    ".rego",
}
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
_DESTRUCTIVE_PATTERNS = (
    re.compile(r"(?i)\brm\s+-rf\s+(?:/|~|\$HOME)(?:\s|$)"),
    re.compile(r"(?i)\b(?:Remove-Item|rmdir|del)\b[^\n]*(?:-Recurse|-Force|/s)"),
    re.compile(r"(?i)\b(?:eval|exec)\s*\("),
    re.compile(r"(?i)\b(?:curl|wget)\b[^\n]*\|\s*(?:sh|bash)\b"),
)
_NETWORK_PATTERN = re.compile(
    r"(?i)\b(?:https?://|requests\.|httpx\.|urllib\.|fetch\s*\(|curl\b|wget\b)"
)
_SHELL_PATTERN = re.compile(
    r"(?i)\b(?:subprocess\.|os\.system|shell\s*=\s*true|powershell\b|cmd\.exe|bash\b)"
)
_OVERRIDE_PATTERN = re.compile(
    r"(?i)\b(?:ignore|disregard|override)\b.{0,50}\b(?:instruction|policy|rule|system)\b"
)
_UNPINNED_DEPENDENCY = re.compile(
    r"^[A-Za-z0-9_.-]+(?:\[[^]]+\])?(?:\s*(?:>=|>|~=|\*)\s*[^;\s]+)?(?:\s*;.*)?$"
)


class SkillValidationError(ValueError):
    pass


def normalize_skill_files(files: list[dict[str, str]]) -> list[dict[str, str]]:
    if not files or len(files) > MAX_SKILL_FILES:
        raise SkillValidationError(f"files must contain 1 to {MAX_SKILL_FILES} entries")
    normalized: list[dict[str, str]] = []
    paths: set[str] = set()
    total_bytes = 0
    for item in files:
        path_value = item.get("path")
        content = item.get("content")
        if not isinstance(path_value, str) or not isinstance(content, str):
            raise SkillValidationError("each file requires string path and content")
        if "\\" in path_value or "\x00" in path_value:
            raise SkillValidationError(f"invalid path: {path_value}")
        path = PurePosixPath(path_value)
        if (
            not path_value
            or path.is_absolute()
            or path_value.startswith("/")
            or ":" in path.parts[0]
            or any(part in {"", ".", ".."} for part in path_value.split("/"))
        ):
            raise SkillValidationError(f"invalid path: {path_value}")
        canonical_path = path.as_posix()
        if canonical_path in paths:
            raise SkillValidationError(f"duplicate path: {canonical_path}")
        if "\x00" in content or _looks_binary(content):
            raise SkillValidationError(f"binary content is not allowed: {canonical_path}")
        normalized_content = content.replace("\r\n", "\n").replace("\r", "\n")
        total_bytes += len(canonical_path.encode()) + len(normalized_content.encode("utf-8"))
        if total_bytes > MAX_SKILL_BYTES:
            raise SkillValidationError("skill package exceeds 1 MiB")
        paths.add(canonical_path)
        normalized.append({"path": canonical_path, "content": normalized_content})
    return sorted(normalized, key=lambda item: item["path"])


def skill_sha256(manifest: dict[str, Any], files: list[dict[str, str]]) -> str:
    payload = {"manifest": manifest, "files": files}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def import_skill(
    session: Session,
    *,
    organization_id: int,
    name: str,
    version: str,
    description: str,
    source_ref: str | None,
    manifest: dict[str, Any],
    files: list[dict[str, str]],
) -> tuple[SkillPackage, SkillVersion]:
    normalized = normalize_skill_files(files)
    digest = skill_sha256(manifest, normalized)
    package = session.scalar(
        select(SkillPackage).where(
            SkillPackage.organization_id == organization_id,
            SkillPackage.name == name,
        )
    )
    if package is None:
        package = SkillPackage(
            organization_id=organization_id,
            name=name,
            description=description,
        )
        session.add(package)
        session.flush()
    existing_version = session.scalar(
        select(SkillVersion).where(
            SkillVersion.package_id == package.id,
            SkillVersion.version == version,
        )
    )
    if existing_version is not None:
        if existing_version.sha256 != digest:
            raise SkillValidationError(
                "skill version is immutable and already has different content"
            )
        return package, existing_version
    existing_digest = session.scalar(
        select(SkillVersion).where(
            SkillVersion.package_id == package.id,
            SkillVersion.sha256 == digest,
        )
    )
    if existing_digest is not None:
        raise SkillValidationError(
            f"identical content is already frozen as version {existing_digest.version}"
        )
    skill_version = SkillVersion(
        package_id=package.id,
        version=version,
        sha256=digest,
        source_ref=source_ref,
        manifest=manifest,
        files=normalized,
    )
    session.add(skill_version)
    session.flush()
    return package, skill_version


def scan_skill_version(skill_version: SkillVersion) -> tuple[str, list[dict[str, Any]], dict]:
    findings: list[dict[str, Any]] = []
    manifest = dict(skill_version.manifest)
    permissions = manifest.get("permissions")
    permissions = permissions if isinstance(permissions, dict) else {}
    declared_network = permissions.get("network", [])
    declared_shell = bool(permissions.get("shell", False))
    network_values = (
        declared_network if isinstance(declared_network, list) else [declared_network]
    )
    if any(value in {True, "*", "0.0.0.0/0", "::/0"} for value in network_values):
        _finding(
            findings,
            "skill.unrestricted_network",
            "block",
            "manifest",
            1,
            "Network permission is unrestricted",
        )
    filesystem = permissions.get("filesystem", {})
    writes = filesystem.get("write", []) if isinstance(filesystem, dict) else []
    writes = writes if isinstance(writes, list) else [writes]
    if any(value in {"/", "*", "**", "C:/", "C:\\"} for value in writes):
        _finding(
            findings,
            "skill.unrestricted_filesystem_write",
            "block",
            "manifest",
            1,
            "Filesystem write permission is unrestricted",
        )

    observed_network = False
    observed_shell = False
    for file in skill_version.files:
        path = str(file["path"])
        content = str(file["content"])
        suffix = PurePosixPath(path).suffix.lower()
        if suffix not in _KNOWN_SUFFIXES:
            _finding(
                findings,
                "skill.unknown_file_type",
                "warn",
                path,
                1,
                "File type is not covered by the deterministic scanner",
            )
        for line_number, line in enumerate(content.splitlines(), 1):
            if any(pattern.search(line) for pattern in _SECRET_PATTERNS):
                _finding(
                    findings,
                    "skill.hardcoded_secret",
                    "block",
                    path,
                    line_number,
                    "Possible hardcoded credential detected; value omitted",
                )
            if any(pattern.search(line) for pattern in _DESTRUCTIVE_PATTERNS):
                _finding(
                    findings,
                    "skill.high_risk_execution",
                    "block",
                    path,
                    line_number,
                    "High-risk delete or dynamic execution command detected",
                )
            if _NETWORK_PATTERN.search(line):
                observed_network = True
            if _SHELL_PATTERN.search(line):
                observed_shell = True
            if _OVERRIDE_PATTERN.search(line):
                _finding(
                    findings,
                    "skill.instruction_override",
                    "warn",
                    path,
                    line_number,
                    "Instruction override language requires review",
                    confidence="heuristic",
                )
        if PurePosixPath(path).name.lower() in {"requirements.txt", "dependencies.txt"}:
            for line_number, line in enumerate(content.splitlines(), 1):
                requirement = line.strip()
                if requirement and not requirement.startswith(("#", "-")):
                    if _UNPINNED_DEPENDENCY.fullmatch(requirement):
                        _finding(
                            findings,
                            "skill.unpinned_dependency",
                            "warn",
                            path,
                            line_number,
                            "Dependency is not pinned with an exact version",
                        )
    if observed_network and not network_values:
        _finding(
            findings,
            "skill.undeclared_network",
            "warn",
            "manifest",
            1,
            "Content uses network access but manifest does not declare it",
        )
    if observed_shell and not declared_shell:
        _finding(
            findings,
            "skill.undeclared_shell",
            "warn",
            "manifest",
            1,
            "Content uses shell execution but manifest does not declare it",
        )
    if declared_shell and not observed_shell:
        _finding(
            findings,
            "skill.unused_shell_permission",
            "warn",
            "manifest",
            1,
            "Manifest declares shell access not observed in package content",
        )
    counts = {
        "block": sum(item["severity"] == "block" for item in findings),
        "warn": sum(item["severity"] == "warn" for item in findings),
    }
    counts["total"] = len(findings)
    status = "block" if counts["block"] else "warn" if counts["warn"] else "pass"
    return status, findings, counts


def create_skill_scan(session: Session, skill_version: SkillVersion) -> SkillScan:
    status, findings, summary = scan_skill_version(skill_version)
    scan = SkillScan(
        skill_version_id=skill_version.id,
        scanner_version=SCANNER_VERSION,
        status=status,
        findings=findings,
        summary=summary,
    )
    session.add(scan)
    session.flush()
    return scan


def attach_skill_version(
    session: Session,
    *,
    organization_id: int,
    agent_version_id: int,
    skill_version_id: int,
) -> AgentVersionSkill:
    version = session.scalar(
        select(AgentVersion)
        .join(EvaluationTarget, EvaluationTarget.id == AgentVersion.target_id)
        .where(
            AgentVersion.id == agent_version_id,
            EvaluationTarget.organization_id == organization_id,
        )
    )
    skill_version = session.scalar(
        select(SkillVersion)
        .join(SkillPackage, SkillPackage.id == SkillVersion.package_id)
        .where(
            SkillVersion.id == skill_version_id,
            SkillPackage.organization_id == organization_id,
        )
    )
    if version is None or skill_version is None:
        raise LookupError("version or skill version not found")
    used = session.scalar(
        select(EvalRun.id).where(
            or_(
                EvalRun.baseline_version_id == agent_version_id,
                EvalRun.candidate_version_id == agent_version_id,
            )
        )
    )
    if used is not None:
        raise SkillValidationError(
            "agent version is frozen because it is referenced by an eval run"
        )
    existing = session.get(AgentVersionSkill, (agent_version_id, skill_version_id))
    if existing is not None:
        return existing
    attachment = AgentVersionSkill(
        agent_version_id=agent_version_id,
        skill_version_id=skill_version_id,
    )
    session.add(attachment)
    session.flush()
    return attachment


def skill_regression(session: Session, run: EvalRun) -> dict[str, Any]:
    baseline = _version_skill_snapshot(session, run.baseline_version_id)
    candidate = _version_skill_snapshot(session, run.candidate_version_id)
    baseline_by_package = {item["package_name"]: item for item in baseline}
    regressions: list[dict[str, Any]] = []
    for item in candidate:
        previous = baseline_by_package.get(item["package_name"])
        before = _summary(previous)
        after = _summary(item)
        if previous is None or after["block"] > before["block"] or after["warn"] > before["warn"]:
            regressions.append(
                {
                    "package_name": item["package_name"],
                    "baseline": before,
                    "candidate": after,
                    "new_package": previous is None,
                }
            )
    new_block = 0
    new_warn = 0
    for item in candidate:
        before = _summary(baseline_by_package.get(item["package_name"]))
        after = _summary(item)
        new_block += max(0, after["block"] - before["block"])
        new_warn += max(0, after["warn"] - before["warn"])
    summary = {"new_block": new_block, "new_warn": new_warn, "regression_count": len(regressions)}
    return {
        "status": "baseline_required" if run.baseline_version_id is None else "ready",
        "baseline": baseline,
        "candidate": candidate,
        "regressions": regressions,
        "summary": summary,
    }


def version_skill_snapshot(session: Session, version_id: int | None) -> list[dict[str, Any]]:
    return _version_skill_snapshot(session, version_id)


def _version_skill_snapshot(session: Session, version_id: int | None) -> list[dict[str, Any]]:
    if version_id is None:
        return []
    rows = session.execute(
        select(AgentVersionSkill, SkillVersion, SkillPackage)
        .join(SkillVersion, SkillVersion.id == AgentVersionSkill.skill_version_id)
        .join(SkillPackage, SkillPackage.id == SkillVersion.package_id)
        .where(AgentVersionSkill.agent_version_id == version_id)
        .order_by(SkillPackage.name, SkillVersion.version)
    )
    snapshots = []
    for _, skill_version, package in rows:
        latest_scan = session.scalar(
            select(SkillScan)
            .where(SkillScan.skill_version_id == skill_version.id)
            .order_by(SkillScan.created_at.desc(), SkillScan.id.desc())
            .limit(1)
        )
        snapshots.append(
            {
                "package_id": package.id,
                "package_name": package.name,
                "skill_version_id": skill_version.id,
                "version": skill_version.version,
                "sha256": skill_version.sha256,
                "scan": None
                if latest_scan is None
                else {
                    "id": latest_scan.id,
                    "scanner_version": latest_scan.scanner_version,
                    "status": latest_scan.status,
                    "summary": latest_scan.summary,
                },
            }
        )
    return snapshots


def _summary(item: dict[str, Any] | None) -> dict[str, int]:
    if not item or not item.get("scan"):
        return {"block": 0, "warn": 0}
    summary = item["scan"].get("summary", {})
    return {"block": int(summary.get("block", 0)), "warn": int(summary.get("warn", 0))}


def _finding(
    findings: list[dict[str, Any]],
    rule_id: str,
    severity: str,
    path: str,
    line: int,
    message: str,
    *,
    confidence: str = "deterministic",
) -> None:
    findings.append(
        {
            "rule_id": rule_id,
            "severity": severity,
            "path": path,
            "line": line,
            "message": message,
            "confidence": confidence,
        }
    )


def _looks_binary(content: str) -> bool:
    if not content:
        return False
    control = sum(ord(char) < 32 and char not in "\n\r\t" for char in content)
    return control / len(content) > 0.01
