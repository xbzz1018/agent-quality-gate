from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from agent_quality_harness.domain.models import (
    AgentVersion,
    AgentVersionSkill,
    EvalCase,
    EvalDataset,
    EvalRun,
    EvaluationTarget,
    SkillPackage,
    SkillScan,
    SkillVersion,
)

MAX_SKILL_FILES = 100
MAX_SKILL_BYTES = 1024 * 1024
SCANNER_VERSION = "skills-static-v1"
SKILL_MANIFEST_SCHEMA = "aqh.skill-manifest/v1"
MAX_BOUND_SKILLS = 64

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


class SkillSecretError(SkillValidationError):
    def __init__(self, findings: list[dict[str, Any]]) -> None:
        super().__init__("hardcoded_secret_detected")
        self.findings = findings


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
    secret_findings = detect_hardcoded_secrets(normalized)
    if secret_findings:
        raise SkillSecretError(secret_findings)
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


def detect_hardcoded_secrets(files: list[dict[str, str]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for file in files:
        path = str(file["path"])
        for line_number, line in enumerate(str(file["content"]).splitlines(), 1):
            if any(pattern.search(line) for pattern in _SECRET_PATTERNS):
                _finding(
                    findings,
                    "skill.hardcoded_secret",
                    "block",
                    path,
                    line_number,
                    "Possible hardcoded credential detected; value omitted",
                )
    return findings


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
    current = list(
        session.scalars(
            select(AgentVersionSkill.skill_version_id).where(
                AgentVersionSkill.agent_version_id == agent_version_id
            )
        )
    )
    replace_skill_bindings(
        session,
        organization_id=organization_id,
        agent_version_id=agent_version_id,
        skill_version_ids=sorted({*current, skill_version_id}),
    )
    attachment = session.get(AgentVersionSkill, (agent_version_id, skill_version_id))
    if attachment is None:
        raise RuntimeError("skill attachment was not persisted")
    return attachment


def validate_skill_bindings(
    session: Session,
    *,
    organization_id: int,
    agent_version_id: int,
    skill_version_ids: list[int],
) -> dict[str, Any]:
    version = session.scalar(
        select(AgentVersion)
        .join(EvaluationTarget, EvaluationTarget.id == AgentVersion.target_id)
        .where(
            AgentVersion.id == agent_version_id,
            EvaluationTarget.organization_id == organization_id,
        )
    )
    if version is None:
        raise LookupError("agent version not found")
    requested = list(dict.fromkeys(skill_version_ids))
    issues: list[dict[str, Any]] = []
    if len(requested) != len(skill_version_ids):
        issues.append(_binding_issue("duplicate_skill_version", "duplicate ids are not allowed"))
    if len(requested) > MAX_BOUND_SKILLS:
        issues.append(
            _binding_issue(
                "too_many_skills",
                f"at most {MAX_BOUND_SKILLS} Skill versions may be bound",
            )
        )
    versions = list(
        session.scalars(
            select(SkillVersion)
        .join(SkillPackage, SkillPackage.id == SkillVersion.package_id)
        .where(
                SkillVersion.id.in_(requested),
            SkillPackage.organization_id == organization_id,
        )
        )
    )
    if len(versions) != len(requested):
        issues.append(
            _binding_issue("skill_not_found", "one or more Skill versions were not found")
        )
    used = session.scalar(
        select(EvalRun.id).where(
            or_(
                EvalRun.baseline_version_id == agent_version_id,
                EvalRun.candidate_version_id == agent_version_id,
            )
        )
    )
    if used is not None:
        issues.append(
            _binding_issue(
                "agent_version_frozen",
                "Agent version is referenced by an EvalRun",
            )
        )
    packages = {
        row.id: row
        for row in session.scalars(
            select(SkillPackage).where(
                SkillPackage.id.in_([item.package_id for item in versions])
            )
        )
    }
    by_name: dict[str, tuple[SkillVersion, SkillPackage]] = {}
    intents: dict[str, str] = {}
    exclusive_groups: dict[str, str] = {}
    strict_manifests = len(versions) > 1
    for skill_version in versions:
        package = packages[skill_version.package_id]
        if package.name in by_name:
            issues.append(
                _binding_issue(
                    "multiple_package_versions",
                    f"multiple versions of {package.name} cannot be bound",
                    skill=package.name,
                )
            )
        by_name[package.name] = (skill_version, package)
        manifest_issues = validate_skill_manifest(skill_version.manifest)
        if strict_manifests and manifest_issues:
            issues.extend(
                {**item, "skill": package.name} for item in manifest_issues
            )
        latest_scan = session.scalar(
            select(SkillScan)
            .where(SkillScan.skill_version_id == skill_version.id)
            .order_by(SkillScan.created_at.desc(), SkillScan.id.desc())
            .limit(1)
        )
        if latest_scan is None:
            issues.append(
                _binding_issue("scan_missing", "Skill version has no scan", skill=package.name)
            )
        elif latest_scan.status == "block":
            issues.append(
                _binding_issue("scan_block", "Skill version scan is BLOCK", skill=package.name)
            )
        routing = skill_version.manifest.get("routing", {})
        routing = routing if isinstance(routing, dict) else {}
        group = routing.get("exclusive_group")
        if isinstance(group, str) and group:
            if group in exclusive_groups:
                issues.append(
                    _binding_issue(
                        "exclusive_group_conflict",
                        f"exclusive group {group} is shared with {exclusive_groups[group]}",
                        skill=package.name,
                    )
                )
            exclusive_groups[group] = package.name
        for intent in routing.get("intents", []):
            if intent in intents:
                issues.append(
                    _binding_issue(
                        "duplicate_routing_intent",
                        f"routing intent {intent} is shared with {intents[intent]}",
                        skill=package.name,
                    )
                )
            intents[str(intent)] = package.name
    for name, (skill_version, _) in by_name.items():
        manifest = skill_version.manifest
        for conflict in manifest.get("conflicts", []):
            if conflict in by_name:
                issues.append(
                    _binding_issue(
                        "declared_conflict",
                        f"{name} conflicts with {conflict}",
                        skill=name,
                    )
                )
        for dependency in manifest.get("dependencies", []):
            if not isinstance(dependency, dict):
                continue
            dependency_name = str(dependency.get("name", ""))
            bound = by_name.get(dependency_name)
            if bound is None:
                issues.append(
                    _binding_issue(
                        "dependency_missing",
                        f"{name} requires {dependency_name}",
                        skill=name,
                    )
                )
                continue
            bound_version = bound[0]
            expected_version = dependency.get("version")
            expected_sha = dependency.get("sha256")
            if expected_version and bound_version.version != expected_version:
                issues.append(
                    _binding_issue(
                        "dependency_version_mismatch",
                        f"{dependency_name} must be version {expected_version}",
                        skill=name,
                    )
                )
            if expected_sha and bound_version.sha256 != expected_sha:
                issues.append(
                    _binding_issue(
                        "dependency_sha_mismatch",
                        f"{dependency_name} SHA-256 does not match",
                        skill=name,
                    )
                )
    return {
        "valid": not issues,
        "agent_version_id": agent_version_id,
        "skill_version_ids": requested,
        "issues": issues,
    }


def replace_skill_bindings(
    session: Session,
    *,
    organization_id: int,
    agent_version_id: int,
    skill_version_ids: list[int],
) -> list[AgentVersionSkill]:
    validation = validate_skill_bindings(
        session,
        organization_id=organization_id,
        agent_version_id=agent_version_id,
        skill_version_ids=skill_version_ids,
    )
    if not validation["valid"]:
        raise SkillValidationError(json.dumps(validation["issues"], ensure_ascii=False))
    session.execute(
        delete(AgentVersionSkill).where(
            AgentVersionSkill.agent_version_id == agent_version_id
        )
    )
    rows = [
        AgentVersionSkill(
            agent_version_id=agent_version_id,
            skill_version_id=skill_version_id,
        )
        for skill_version_id in validation["skill_version_ids"]
    ]
    session.add_all(rows)
    session.flush()
    return rows


def validate_skill_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest.get("schema") != SKILL_MANIFEST_SCHEMA:
        return [_binding_issue("manifest_schema", f"schema must be {SKILL_MANIFEST_SCHEMA}")]
    issues: list[dict[str, Any]] = []
    routing = manifest.get("routing")
    if not isinstance(routing, dict):
        issues.append(_binding_issue("routing_missing", "routing must be an object"))
    else:
        intents = routing.get("intents")
        if not isinstance(intents, list) or not intents or any(
            not isinstance(item, str) or not item for item in intents
        ):
            issues.append(
                _binding_issue("routing_intents", "routing.intents must contain strings")
            )
    dependencies = manifest.get("dependencies", [])
    if not isinstance(dependencies, list):
        issues.append(_binding_issue("dependencies", "dependencies must be a list"))
    else:
        for dependency in dependencies:
            if (
                not isinstance(dependency, dict)
                or not isinstance(dependency.get("name"), str)
                or not dependency.get("name")
                or not dependency.get("version")
                and not dependency.get("sha256")
            ):
                issues.append(
                    _binding_issue(
                        "dependency_not_exact",
                        "each dependency requires name and exact version or SHA-256",
                    )
                )
    conflicts = manifest.get("conflicts", [])
    if not isinstance(conflicts, list) or any(not isinstance(item, str) for item in conflicts):
        issues.append(_binding_issue("conflicts", "conflicts must be a string list"))
    return issues


def skill_coverage(
    session: Session,
    *,
    organization_id: int,
    dataset_id: int,
    agent_version_id: int,
) -> dict[str, Any]:
    dataset = session.scalar(
        select(EvalDataset).where(
            EvalDataset.id == dataset_id,
            EvalDataset.organization_id == organization_id,
        )
    )
    version = session.scalar(
        select(AgentVersion)
        .join(EvaluationTarget, EvaluationTarget.id == AgentVersion.target_id)
        .where(
            AgentVersion.id == agent_version_id,
            EvaluationTarget.organization_id == organization_id,
        )
    )
    if dataset is None or version is None:
        raise LookupError("dataset or agent version not found")
    bound = _version_skill_snapshot(session, agent_version_id)
    cases = list(session.scalars(select(EvalCase).where(EvalCase.dataset_id == dataset_id)))
    coverage_rows = []
    interactions = []
    covered = required = 0
    for skill in bound:
        name = skill["package_name"]
        positives = 0
        negatives = 0
        for case in cases:
            rules = case.expected.get("skills") if isinstance(case.expected, dict) else None
            if not isinstance(rules, dict):
                continue
            positives += int(name in rules.get("required", []))
            negatives += int(name in rules.get("forbidden", []))
        coverage_rows.append(
            {"skill": name, "positive_cases": positives, "negative_cases": negatives}
        )
        required += 2
        covered += int(positives > 0) + int(negatives > 0)
    bound_versions = {
        item["package_name"]: session.get(SkillVersion, item["skill_version_id"])
        for item in bound
    }
    seen_interactions: set[tuple[str, str, str]] = set()
    for name, skill_version in bound_versions.items():
        if skill_version is None:
            continue
        for dependency in skill_version.manifest.get("dependencies", []):
            if not isinstance(dependency, dict):
                continue
            other = str(dependency.get("name", ""))
            key = ("dependency", name, other)
            if not other or key in seen_interactions:
                continue
            seen_interactions.add(key)
            matched = any(_case_has_skill_order(case, [other, name]) for case in cases)
            interactions.append(
                {"type": "dependency", "skill": name, "other": other, "covered": matched}
            )
            required += 1
            covered += int(matched)
        for conflict in skill_version.manifest.get("conflicts", []):
            other = str(conflict)
            pair = tuple(sorted((name, other)))
            key = ("conflict", pair[0], pair[1])
            if not other or key in seen_interactions:
                continue
            seen_interactions.add(key)
            matched = any(_case_disambiguates(case, name, other) for case in cases)
            interactions.append(
                {"type": "conflict", "skill": name, "other": other, "covered": matched}
            )
            required += 1
            covered += int(matched)
    ratio = covered / required if required else 1.0
    return {
        "dataset_id": dataset_id,
        "agent_version_id": agent_version_id,
        "bound_skill_count": len(bound),
        "covered_requirements": covered,
        "total_requirements": required,
        "coverage_ratio": ratio,
        "skills": coverage_rows,
        "interactions": interactions,
    }


def _binding_issue(code: str, message: str, *, skill: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "skill": skill}


def _case_skill_rules(case: EvalCase) -> dict[str, Any]:
    rules = case.expected.get("skills") if isinstance(case.expected, dict) else None
    return rules if isinstance(rules, dict) else {}


def _case_has_skill_order(case: EvalCase, wanted: list[str]) -> bool:
    order = _case_skill_rules(case).get("order", [])
    positions = [order.index(name) for name in wanted if name in order]
    return len(positions) == len(wanted) and positions == sorted(positions)


def _case_disambiguates(case: EvalCase, first: str, second: str) -> bool:
    rules = _case_skill_rules(case)
    required = set(rules.get("required", []))
    forbidden = set(rules.get("forbidden", []))
    return (first in required and second in forbidden) or (
        second in required and first in forbidden
    )


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
