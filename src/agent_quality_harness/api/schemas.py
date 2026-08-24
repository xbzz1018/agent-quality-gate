from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_quality_harness.domain.enums import (
    GateDecision,
    MeasurementStatus,
    RunStatus,
    TargetKind,
    TargetProtocol,
    VersionRole,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[PageItem](ApiModel):
    items: list[PageItem]
    total: int
    page: int
    page_size: int


class TargetCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    target_kind: TargetKind = TargetKind.AGENT
    protocol: TargetProtocol
    endpoint: str = Field(min_length=1)
    auth_ref: str | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    capabilities: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_adapter_family(self) -> "TargetCreate":
        agent_protocols = {
            TargetProtocol.HTTP,
            TargetProtocol.SSE,
            TargetProtocol.AG_UI,
            TargetProtocol.A2A,
        }
        if self.target_kind is TargetKind.AGENT and self.protocol not in agent_protocols:
            raise ValueError("agent targets require HTTP, SSE, AG-UI, or A2A")
        if self.target_kind is TargetKind.TOOL and self.protocol is not TargetProtocol.MCP:
            raise ValueError("tool targets require MCP")
        return self


class TargetRead(ApiModel):
    id: int
    organization_id: int
    name: str
    target_kind: TargetKind
    protocol: TargetProtocol
    endpoint: str
    auth_ref: str | None
    timeout_seconds: int
    capabilities: dict[str, Any]
    enabled: bool
    created_at: datetime


class VersionCreate(ApiModel):
    version: str = Field(min_length=1, max_length=200)
    model: str | None = None
    prompt_version: str | None = None
    tool_schema_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class VersionRead(ApiModel):
    id: int
    target_id: int
    version: str
    model: str | None
    prompt_version: str | None
    tool_schema_hash: str | None


class SkillFileCreate(ApiModel):
    path: str = Field(min_length=1, max_length=500)
    content: str


class SkillImport(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    source_ref: str | None = Field(default=None, max_length=1000)
    manifest: dict[str, Any] = Field(default_factory=dict)
    files: list[SkillFileCreate] = Field(min_length=1, max_length=100)


class SkillVersionRead(ApiModel):
    id: int
    package_id: int
    version: str
    sha256: str
    source_ref: str | None
    manifest: dict[str, Any]
    frozen_at: datetime


class SkillPackageRead(ApiModel):
    id: int
    organization_id: int
    name: str
    description: str
    created_at: datetime


class SkillImportRead(ApiModel):
    package: SkillPackageRead
    version: SkillVersionRead


class SkillScanRead(ApiModel):
    id: int
    skill_version_id: int
    scanner_version: str
    status: Literal["pass", "warn", "block"]
    findings: list[dict[str, Any]]
    summary: dict[str, Any]
    created_at: datetime


class AgentVersionSkillRead(ApiModel):
    agent_version_id: int
    skill_version_id: int
    attached_at: datetime


class SkillBindingSet(ApiModel):
    skill_version_ids: list[int] = Field(default_factory=list, max_length=64)


class SkillBindingValidationRead(ApiModel):
    valid: bool
    agent_version_id: int
    skill_version_ids: list[int]
    issues: list[dict[str, Any]]


class PolicyBundleCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    package_path: str = Field(min_length=1, max_length=300)
    entrypoint: str = Field(default="decision", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    rego: str = Field(min_length=1, max_length=200_000)
    data: dict[str, Any] = Field(default_factory=dict)


class PolicyBundleRead(PolicyBundleCreate):
    id: int
    organization_id: int
    sha256: str
    status: Literal["validated", "invalid"]
    validation_errors: list[dict[str, Any]]
    created_at: datetime


class PolicyEvaluationRead(ApiModel):
    id: int
    run_id: int
    policy_bundle_id: int
    decision_id: str | None
    input_sha256: str
    decision: Literal["ship", "warn", "block"]
    reasons: list[dict[str, Any]]
    latency_ms: int | None
    error: str | None
    evaluated_at: datetime
    metadata_json: dict[str, Any]
    created_at: datetime


class DemoBootstrapCreate(ApiModel):
    agent_endpoint: str | None = None


class DemoBootstrapRead(ApiModel):
    demo_fixture: bool = True
    target_id: int
    baseline_version_id: int
    candidate_version_id: int
    dataset_id: int
    gate_policy_id: int
    pricing_snapshot_id: int
    created_resources: list[str]


class DatasetCaseImport(ApiModel):
    id: str = Field(min_length=1, max_length=200)
    input: dict[str, Any]
    expected: "ExpectedRules" = Field(default_factory=lambda: ExpectedRules())
    tags: list[str] = Field(default_factory=list)


class DatasetImport(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=200)
    split: str = Field(default="test", min_length=1, max_length=50)
    provenance: dict[str, Any] = Field(default_factory=dict)
    cases: list[DatasetCaseImport] = Field(min_length=1)


class DatasetRead(ApiModel):
    id: int
    organization_id: int
    name: str
    version: str
    split: str
    sha256: str
    provenance: dict[str, Any]
    frozen_at: datetime
    case_count: int


class DatasetCaseRead(ApiModel):
    id: int
    external_id: str
    ordinal: int
    input_data: dict[str, Any]
    expected: dict[str, Any]
    tags: list[str]
    sha256: str


class DatasetDetail(DatasetRead):
    cases: list[DatasetCaseRead]


class EvalRunCreate(ApiModel):
    dataset_id: int
    candidate_version_id: int
    baseline_version_id: int | None = None
    gate_policy_id: int | None = None
    pricing_snapshot_id: int | None = None
    benchmark_mode: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class EvalRunRead(ApiModel):
    id: int
    organization_id: int
    dataset_id: int
    baseline_version_id: int | None
    candidate_version_id: int
    replay_of_run_id: int | None
    status: RunStatus
    config: dict[str, Any]
    manifest: dict[str, Any]
    benchmark_mode: bool
    expected_case_count: int
    completed_case_count: int
    failure_reason: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class Readiness(ApiModel):
    status: str
    components: dict[str, str]


class UsageRead(ApiModel):
    measurement_status: MeasurementStatus
    cost_status: MeasurementStatus
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    reasoning_tokens: int | None
    embedding_tokens: int | None
    vision_tokens: int | None
    judge_tokens: int | None
    model_cost: Decimal | None
    external_tool_cost: Decimal | None
    cost_components: dict[str, Any]


class CaseResultRead(ApiModel):
    id: int
    run_id: int
    case_id: int
    version_role: VersionRole
    attempt: int
    output: dict[str, Any] | None
    final_action: str | None
    trace_id: str | None
    trace_url: str | None = None
    scores: dict[str, Any]
    failure_type: str | None
    latency_ms: int | None
    usage: UsageRead | None = None


class RunEventRead(ApiModel):
    id: int
    run_id: int
    case_result_id: int | None
    event_type: str
    source: str
    payload: dict[str, Any]
    redacted: bool
    occurred_at: datetime


class ReplayCreate(ApiModel):
    case_ids: list[str] | None = None


class SkillGateControls(ApiModel):
    enabled: bool = False
    require_telemetry: bool = True
    minimum_selection_accuracy: float = Field(default=1.0, ge=0, le=1)
    block_unbound: bool = True
    block_lifecycle_errors: bool = True
    minimum_coverage_ratio: float = Field(default=1.0, ge=0, le=1)
    redundant_call_growth_warn: float = Field(default=0.20, ge=0)


class EvidenceGateControls(ApiModel):
    enabled: bool = False
    minimum_coverage: float = Field(default=1.0, ge=0, le=1)
    block_invalid_refs: bool = True
    block_unsupported_claims: bool = True


class GateControls(ApiModel):
    skill: SkillGateControls = Field(default_factory=SkillGateControls)
    evidence: EvidenceGateControls = Field(default_factory=EvidenceGateControls)


class GatePolicyCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    thresholds: dict[str, float] = Field(default_factory=dict)
    controls: GateControls = Field(default_factory=GateControls)
    policy_bundle_id: int | None = None
    active: bool = True


class GatePolicyRead(GatePolicyCreate):
    id: int
    organization_id: int
    created_at: datetime


class GateResultRead(ApiModel):
    id: int
    run_id: int
    policy_id: int
    policy_evaluation_id: int | None
    decision: GateDecision
    reasons: list[dict[str, Any]]
    metric_deltas: dict[str, Any]
    evaluated_at: datetime


class BaselineRequiredRead(ApiModel):
    status: Literal["baseline_required"] = "baseline_required"
    run_id: int
    detail: str = "A baseline version is required for comparison and release-gate evaluation"
    candidate: dict[str, Any] | None = None


class PricingSnapshotCreate(ApiModel):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    effective_at: datetime
    prices: dict[str, Decimal]
    source: str = Field(min_length=1)


class PricingSnapshotRead(PricingSnapshotCreate):
    id: int
    organization_id: int
    created_at: datetime


class AssertionRule(ApiModel):
    id: str | None = None
    path: str = ""
    operator: Literal["equals", "not_equals", "contains", "exists", "gte", "lte", "regex"] = (
        "equals"
    )
    value: Any = None
    critical: bool = True


class OutputRules(ApiModel):
    equals: Any = None
    assertions: list[AssertionRule] = Field(default_factory=list)
    json_schema: dict[str, Any] | None = None


class ToolArgumentRule(ApiModel):
    id: str | None = None
    name: str
    equals: dict[str, Any] = Field(default_factory=dict)


class ToolRules(ApiModel):
    required: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    order: list[str] | None = None
    arguments: list[ToolArgumentRule] = Field(default_factory=list)


class SkillRules(ApiModel):
    required: list[str] = Field(default_factory=list)
    allowed: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    order: list[str] | None = None
    max_calls: int | None = Field(default=None, ge=0)
    allow_repeats: bool = False
    telemetry_required: bool = False
    arguments_sha256: dict[str, str] = Field(default_factory=dict)


class EvidenceClaimRule(ApiModel):
    id: str = Field(min_length=1, max_length=200)
    allowed_refs: list[str] = Field(default_factory=list)


class EvidenceRules(ApiModel):
    required: bool = False
    allowed_refs: list[str] = Field(default_factory=list)
    required_claims: list[EvidenceClaimRule] = Field(default_factory=list)
    minimum_coverage: float = Field(default=1.0, ge=0, le=1)


class CitationRules(ApiModel):
    required: bool = False
    min_count: int = Field(default=0, ge=0)
    critical: bool = True


class SafetyRules(ApiModel):
    forbidden_patterns: list[str] = Field(default_factory=list)


class ExpectedRules(ApiModel):
    final_action: str | list[str] | None = None
    output: OutputRules | None = None
    tools: ToolRules | None = None
    skills: SkillRules | None = None
    citations: CitationRules | None = None
    evidence: EvidenceRules | None = None
    safety: SafetyRules | None = None
    business: list[AssertionRule] = Field(default_factory=list)
